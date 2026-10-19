#!/usr/bin/env bash
# Deploy da-registry to the dev cluster's `da` namespace with helm.
#
# The Jenkinsfile's Deploy stage runs this on the vpn-agent2 node with the
# da-dev-kubeconfig credential (the da-ci service account of the RKE2 cluster at
# https://10.0.1.58:6443). It is a script, not inline Groovy, so a deploy by hand
# is the same command:
#
#   KUBECONFIG=<kubeconfig> AWS_ACCOUNT_ID=<id> ./ci/deploy-da-dev.sh <image-tag>
#
# Adapted from the crop pipeline's ci/deploy-crop-dev.sh. What it does, in order:
#   1. Preflight: print the API server and identity; stop at once if the server
#      is not the dev cluster, cannot be reached, the namespace is missing or the
#      account cannot deploy into it.
#   2. Refresh the ECR pull secret from the token the build agent stashed.
#   3. helm dependency build.
#   4. Write the values this build owns: the five image tags and the hook
#      switches. Everything else comes from the chart's values.yaml and
#      values-dev.yaml in git, so nothing is set on the cluster by hand.
#   5. Render, refuse a render that still carries a placeholder host, then
#      helm upgrade --install.
#   6. While helm waits on the hook Jobs, print them every minute and save hook
#      pod logs (hook pods are deleted when they fail). On failure print those
#      logs, the API pod logs, release history and warning events.
#   7. Wait for every Deployment to roll out and print the hook Jobs' outcome.
#
# Env:
#   TAG               image tag to deploy (or first argument)          required
#   AWS_ACCOUNT_ID    owner of the ECR registry                         required
#   KUBECONFIG        kubeconfig for the dev cluster                    required
#   AWS_REGION        default ap-south-1
#   ECR_PATH          default openg2p/da-registry
#   HELM_RELEASE      default da-registry (the chart derives the Keycloak client,
#                     database, secret and callback names from it: keep it)
#   HELM_NAMESPACE    default da
#   EXPECTED_SERVER   default https://10.0.1.58:6443; refuse any other API server
#                     (empty disables the check)
#   HELM_CHART_DIR    default helm/openg2p-da-registry
#   VALUES_FILE       default <chart>/values-dev.yaml
#   RUN_DB_SEED       true|false, default true   run the db-seed hook Job
#   RUN_IAM_REGISTER  true|false, default auto   run the IAM registration hook Job;
#                     auto = only when the release does not exist yet (the tile
#                     is registered once; re-registering holds the deploy)
#   HELM_TIMEOUT      default 20m
#   ROLLOUT_TIMEOUT   per-Deployment rollout wait, default 420s
#   PULL_SECRET       ECR imagePullSecret to write/use, default da-registry-ecr
set -euo pipefail

TAG="${1:-${TAG:-}}"
[ -n "$TAG" ] || { echo "usage: $0 <image-tag>" >&2; exit 2; }
: "${AWS_ACCOUNT_ID:?set AWS_ACCOUNT_ID}"
: "${KUBECONFIG:?set KUBECONFIG}"
AWS_REGION="${AWS_REGION:-ap-south-1}"
ECR_PATH="${ECR_PATH:-openg2p/da-registry}"
HELM_RELEASE="${HELM_RELEASE:-da-registry}"
HELM_NAMESPACE="${HELM_NAMESPACE:-da}"
EXPECTED_SERVER="${EXPECTED_SERVER-https://10.0.1.58:6443}"
HELM_CHART_DIR="${HELM_CHART_DIR:-helm/openg2p-da-registry}"
VALUES_FILE="${VALUES_FILE:-$HELM_CHART_DIR/values-dev.yaml}"
RUN_DB_SEED="${RUN_DB_SEED:-true}"
RUN_IAM_REGISTER="${RUN_IAM_REGISTER:-auto}"
HELM_TIMEOUT="${HELM_TIMEOUT:-20m}"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-420s}"
PULL_SECRET="${PULL_SECRET:-da-registry-ecr}"
ECR_HOST="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
ECR="${ECR_HOST}/${ECR_PATH}"

[ -r "$VALUES_FILE" ] || { echo "ERROR: values file ${VALUES_FILE} not found" >&2; exit 2; }

NS=(-n "$HELM_NAMESPACE")
WORK="$(mktemp -d)"
BG_PIDS=()
cleanup() {
  [ "${#BG_PIDS[@]}" -eq 0 ] || kill "${BG_PIDS[@]}" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

say() { echo "=== $* ==="; }

# ── 1. Preflight ───────────────────────────────────────────────────────────────
say "Deploy target"
SERVER="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
echo "server:    ${SERVER}"
# The server comes from the kubeconfig credential, not this repo. A credential
# holding another cluster's kubeconfig would deploy there without complaint.
if [ -n "$EXPECTED_SERVER" ] && [ "${SERVER%/}" != "${EXPECTED_SERVER%/}" ]; then
  echo "ERROR: KUBECONFIG points at ${SERVER:-<none>}, expected ${EXPECTED_SERVER}." >&2
  echo "  Replace the Jenkins credential (da-dev-kubeconfig) with the da-ci kubeconfig" >&2
  echo "  for ${EXPECTED_SERVER} (see ci/k8s/README.md)." >&2
  exit 1
fi
echo "namespace: ${HELM_NAMESPACE}"
echo "release:   ${HELM_RELEASE}"
echo "images:    ${ECR}/*:${TAG}"
echo "values:    ${HELM_CHART_DIR}/values.yaml + ${VALUES_FILE}"

if ! CONN="$(kubectl get --raw /version --request-timeout=15s 2>&1)"; then
  echo "ERROR: cannot connect to the API server:" >&2
  echo "$CONN" | tail -3 >&2
  echo "  timeout = no route on TCP 6443; x509 = wrong CA/address; Unauthorized = bad token." >&2
  exit 1
fi
kubectl auth whoami 2>/dev/null || true

# The service account cannot create namespaces; DevOps creates `da` once.
if ! kubectl get namespace "$HELM_NAMESPACE" >/dev/null 2>&1; then
  echo "ERROR: namespace ${HELM_NAMESPACE} does not exist (or this account may not see it)." >&2
  echo "  A cluster admin creates it with the da-ci service account: see ci/k8s/README.md." >&2
  exit 1
fi

MISSING=""
# Every kind the chart and this script touch. A Role that covers only some of
# them fails deep inside helm instead; a namespace-scoped bind to the built-in
# `admin` ClusterRole plus the Istio kinds covers the lot (ci/k8s/da-ci-dev.yaml).
for CHECK in "list secrets" "create secrets" "create deployments" "create statefulsets" \
             "create jobs" "create cronjobs" "create services" "create configmaps" \
             "create persistentvolumeclaims" "create serviceaccounts" "patch serviceaccounts" \
             "get networkpolicies" "create networkpolicies" "create pods/exec" \
             "create virtualservices.networking.istio.io"; do
  # can-i exits 1 on "no"; compare the printed answer instead.
  # shellcheck disable=SC2086
  ANSWER="$(kubectl auth can-i ${CHECK} "${NS[@]}" 2>/dev/null || true)"
  echo "can-i ${CHECK}: ${ANSWER:-error}"
  [ "$ANSWER" = "yes" ] || MISSING="${MISSING} '${CHECK}'"
done
if [ -n "$MISSING" ]; then
  echo "ERROR: this account may not${MISSING} in namespace ${HELM_NAMESPACE}." >&2
  echo "  Bind it to the admin ClusterRole in that namespace (see ci/k8s/da-ci-dev.yaml)." >&2
  exit 1
fi

# ── 2. ECR pull secret ─────────────────────────────────────────────────────────
# ECR tokens last 12 hours. The build agent mints one (only it has AWS
# credentials) and stashes it as .ecr-token; each deploy writes it into the
# namespace's pull secret. Without the file (a manual run) an existing secret is
# left as it is.
if [ -r .ecr-token ]; then
  say "Refreshing the ${PULL_SECRET} pull secret"
  REG="$(cat .ecr-registry 2>/dev/null || echo "$ECR_HOST")"
  kubectl create secret docker-registry "$PULL_SECRET" "${NS[@]}" \
    --docker-server="$REG" --docker-username=AWS \
    --docker-password="$(cat .ecr-token)" \
    --dry-run=client -o yaml | kubectl apply "${NS[@]}" -f -
  rm -f .ecr-token .ecr-registry
  USE_PULL_SECRET=true
elif kubectl get secret "$PULL_SECRET" "${NS[@]}" >/dev/null 2>&1; then
  echo "No .ecr-token in this workspace; keeping the existing ${PULL_SECRET} secret."
  USE_PULL_SECRET=true
else
  echo "No .ecr-token and no ${PULL_SECRET} secret: pods must pull ECR images by node credentials."
  USE_PULL_SECRET=false
fi
# The secret goes on the namespace's `default` ServiceAccount, which every pod
# of this release (hook Jobs included) uses. The pinned openg2p-registry chart
# has no global.imagePullSecrets value, and the crop pipeline found that the
# idgenerator subchart mis-renders one anyway.
if [ "$USE_PULL_SECRET" = "true" ]; then
  kubectl patch serviceaccount default "${NS[@]}" \
    -p "{\"imagePullSecrets\":[{\"name\":\"${PULL_SECRET}\"}]}" >/dev/null
  echo "default ServiceAccount now pulls with ${PULL_SECRET}"
fi

# ── 3. Chart dependencies ──────────────────────────────────────────────────────
say "helm dependency build"
helm repo add openg2p https://openg2p.github.io/openg2p-helm >/dev/null 2>&1 || true
helm repo update openg2p >/dev/null
# Chart.lock and charts/*.tgz are gitignored, so neither checkout nor unstash
# clears them: a lock left by an older build pins the previous openg2p-registry
# version and `helm dependency build` fails with "out of sync". Resolve fresh.
rm -f "$HELM_CHART_DIR/Chart.lock" "$HELM_CHART_DIR"/charts/*.tgz
helm dependency build "$HELM_CHART_DIR"

# ── 4. Values this build owns ──────────────────────────────────────────────────
# A release left pending by an interrupted run blocks every upgrade with
# "another operation is in progress"; say so plainly instead.
RELEASE_EXISTS=true
STATUS="$(helm status "$HELM_RELEASE" "${NS[@]}" -o json 2>/dev/null | sed -n 's/.*"status":"\([a-z-]*\)".*/\1/p' | head -1 || true)"
case "$STATUS" in
  "") RELEASE_EXISTS=false; echo "No ${HELM_RELEASE} release yet: first install." ;;
  pending-*)
    echo "ERROR: release ${HELM_RELEASE} is '${STATUS}' from an interrupted deploy." >&2
    echo "  Roll back to the last good revision: helm -n ${HELM_NAMESPACE} history ${HELM_RELEASE}; helm -n ${HELM_NAMESPACE} rollback ${HELM_RELEASE} <rev>" >&2
    exit 1 ;;
  *) echo "release ${HELM_RELEASE} is ${STATUS}" ;;
esac
if [ "$RUN_IAM_REGISTER" = "auto" ]; then
  [ "$RELEASE_EXISTS" = "true" ] && RUN_IAM_REGISTER=false || RUN_IAM_REGISTER=true
fi

# Only the image references and the hook switches. Hosts, commons endpoints and
# secret references live in values-dev.yaml, in git. celeryWorker and celeryBeat
# run the same image.
cat > "$WORK/ci-images.yaml" <<EOF
registry:
  staffApi:
    image: {repository: '${ECR}/staff-api', tag: '${TAG}'}
  staffUi:
    image: {repository: '${ECR}/staff-ui', tag: '${TAG}'}
  partnerApi:
    image: {repository: '${ECR}/partner-api', tag: '${TAG}'}
  celeryWorker:
    image: {repository: '${ECR}/celery', tag: '${TAG}'}
  celeryBeat:
    image: {repository: '${ECR}/celery', tag: '${TAG}'}
  dbSeed:
    enabled: ${RUN_DB_SEED}
    image: {repository: '${ECR}/db-seed', tag: '${TAG}'}
  iamRegister:
    enabled: ${RUN_IAM_REGISTER}
EOF
echo "hooks: db-seed=${RUN_DB_SEED}  iam-register=${RUN_IAM_REGISTER}"
VALUES=(-f "$VALUES_FILE" -f "$WORK/ci-images.yaml")

# ── 5. Render, guard, upgrade ──────────────────────────────────────────────────
# Render exactly what the upgrade applies: a chart or values mistake fails here,
# before anything is changed.
helm template "$HELM_RELEASE" "$HELM_CHART_DIR" "${NS[@]}" "${VALUES[@]}" > "$WORK/rendered.yaml"
echo "rendered $(wc -l < "$WORK/rendered.yaml") lines of manifests"
# The subchart defaults every host to *.openg2p.org, a domain that exists
# nowhere here. A render that still carries one means values-dev.yaml missed a
# key, and the release would come up unreachable (the livestock pipeline's guard).
if grep -q 'openg2p\.org' "$WORK/rendered.yaml"; then
  echo "ERROR: rendered manifests still reference the placeholder domain openg2p.org:" >&2
  grep -n 'openg2p\.org' "$WORK/rendered.yaml" | head -20 >&2
  exit 1
fi

# Hook pods are deleted as soon as their Job fails, so save their logs as we go.
# Only this release's own hook pods: <release>-<job>...-<5 chars>.
HOOK_POD_RE="^pod/${HELM_RELEASE}-(db-seed|iam-register|postgres-init|keycloak-init|idgen-pg-init)[a-z0-9_-]*-[a-z0-9]{5}$"
mkdir -p "$WORK/logs"
(
  set +x
  while :; do
    for P in $(kubectl get pods "${NS[@]}" -o name 2>/dev/null | grep -E "$HOOK_POD_RE" || true); do
      N="${P#pod/}"
      kubectl logs "$N" "${NS[@]}" --all-containers --prefix --tail=200 > "$WORK/logs/$N.tmp" 2>/dev/null \
        && mv "$WORK/logs/$N.tmp" "$WORK/logs/$N.log" || rm -f "$WORK/logs/$N.tmp"
    done
    sleep 10
  done
) &
BG_PIDS+=("$!")

# helm prints nothing while it waits on hooks; show which Job it is waiting on.
(
  set +x
  while :; do
    sleep 60
    echo "--- $(date -u +%H:%M:%S) UTC: ${HELM_RELEASE} jobs ---"
    kubectl get jobs "${NS[@]}" --no-headers 2>/dev/null | grep -E "^${HELM_RELEASE}-" || true
  done
) &
BG_PIDS+=("$!")

say "helm upgrade started $(date -u +%H:%M:%S) UTC (timeout ${HELM_TIMEOUT})"
if ! helm upgrade --install "$HELM_RELEASE" "$HELM_CHART_DIR" "${NS[@]}" \
      "${VALUES[@]}" --timeout "$HELM_TIMEOUT"; then
  kill "${BG_PIDS[@]}" 2>/dev/null || true
  BG_PIDS=()
  for F in "$WORK"/logs/*.log; do
    [ -f "$F" ] || continue
    say "hook pod log: $(basename "$F" .log)" >&2
    cat "$F" >&2
  done
  for D in staff-portal-api partner-api; do
    say "${HELM_RELEASE}-${D} pod log" >&2
    kubectl logs "deploy/${HELM_RELEASE}-${D}" "${NS[@]}" --all-containers --prefix --tail=60 >&2 || true
  done
  say "release history" >&2
  helm history "$HELM_RELEASE" "${NS[@]}" --max 5 >&2 || true
  say "recent warning events" >&2
  kubectl get events "${NS[@]}" --field-selector type=Warning --sort-by=.lastTimestamp 2>/dev/null | tail -20 >&2 || true
  exit 1
fi
kill "${BG_PIDS[@]}" 2>/dev/null || true
BG_PIDS=()
say "helm upgrade finished $(date -u +%H:%M:%S) UTC"

# ── 6. Rollout ─────────────────────────────────────────────────────────────────
# staff-portal-api runs `migrate` before it serves (the DA extension adds its
# columns and indexes there), and the old pod has to finish terminating first,
# so 180s was not enough for crop. On a timeout, say which pods are in the way.
for D in staff-portal-api staff-portal-ui partner-api celery-worker celery-beat-producer; do
  if ! kubectl rollout status "deployment/${HELM_RELEASE}-${D}" "${NS[@]}" --timeout="$ROLLOUT_TIMEOUT"; then
    echo "ERROR: ${HELM_RELEASE}-${D} did not roll out within ${ROLLOUT_TIMEOUT}." >&2
    kubectl get pods "${NS[@]}" -l "app.kubernetes.io/instance=${HELM_RELEASE}" -o wide >&2 || true
    kubectl describe deploy "${HELM_RELEASE}-${D}" "${NS[@]}" 2>&1 | sed -n '/Conditions:/,$p' | head -20 >&2 || true
    echo "--- ${D} pod logs (last 60 lines) ---" >&2
    kubectl logs "deploy/${HELM_RELEASE}-${D}" "${NS[@]}" --all-containers --prefix --tail=60 >&2 || true
    kubectl get events "${NS[@]}" --field-selector type=Warning --sort-by=.lastTimestamp 2>/dev/null | tail -10 >&2 || true
    exit 1
  fi
done

say "Deployed ${TAG} to ${HELM_NAMESPACE}"
kubectl get deploy "${NS[@]}" -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,IMAGE:.spec.template.spec.containers[0].image \
  | grep -E "^NAME|^${HELM_RELEASE}-" || true

# The hook Jobs' own outcome: helm only says the release succeeded, not whether
# a Job it waited on had to retry.
for JOB in db-seed iam-register; do
  kubectl get job "${HELM_RELEASE}-${JOB}" "${NS[@]}" >/dev/null 2>&1 || continue
  echo "${HELM_RELEASE}-${JOB}: $(kubectl get job "${HELM_RELEASE}-${JOB}" "${NS[@]}" \
    -o jsonpath='{.status.succeeded} succeeded / {.status.failed} failed' 2>/dev/null)"
done
