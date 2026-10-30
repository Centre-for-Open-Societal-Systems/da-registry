#!/usr/bin/env bash
# Upgrade the DA registry release on the dev cluster with the pinned central chart.
#
# The Jenkinsfile's "Deploy to Development" stage runs this on the vpn-agent2 node
# with the da-dev-kubeconfig credential. A deploy by hand is the same command:
#
#   KUBECONFIG=<kubeconfig> AWS_ACCOUNT_ID=<id> ./ci/deploy-dev.sh <12-char-commit-sha>
#
# What it does, in order:
#   1. Refuse to run unless ci/deploy/oan-chart.json is a complete, deployable pin.
#   2. Download the exact chart archive and public values from oan-helm and verify
#      their SHA-256 (ci/deploy/oan_chart.py).
#   3. Require the release to exist. This script never installs and never uninstalls,
#      and it never touches a database: a wrong name or namespace fails here.
#   4. Render what the upgrade would apply, then `helm upgrade --reset-values` with the
#      pinned public values and this build's images on top. Nothing is carried over
#      from the live release, so the release is exactly what the pin and this build say.
#   5. Wait for the application Deployments to roll out.
#   6. If the upgrade or the rollout fails: save pods, events and logs to
#      deploy-failure-<build>.txt (Jenkins archives it), then `helm rollback` to the last
#      revision that was `deployed` before this build, and fail the build. A rollback
#      restores the chart and values only; it cannot undo database changes made by a
#      db-seed or init hook, so a failure that already migrated data still needs a look.
#
# Env:
#   IMAGE_TAG        first argument: the 12-character commit the images were built from  required
#   AWS_ACCOUNT_ID   owner of the ECR registry                                           required
#   KUBECONFIG       kubeconfig for the dev cluster                                      required
#   AWS_REGION       default ap-south-1
#   ECR_REPO         default openg2p/da-registry
#   HELM_TIMEOUT     default 20m
#   ROLLOUT_TIMEOUT  per-Deployment rollout wait, default 420s
# Release, namespace, chart version and values come from ci/deploy/oan-chart.json only.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

TAG="${1:-${IMAGE_TAG:-}}"
[ -n "$TAG" ] || { echo "usage: $0 <image-tag>" >&2; exit 2; }
: "${AWS_ACCOUNT_ID:?set AWS_ACCOUNT_ID}"
: "${KUBECONFIG:?set KUBECONFIG}"
AWS_REGION="${AWS_REGION:-ap-south-1}"
ECR_REPO="${ECR_REPO:-openg2p/da-registry}"
HELM_TIMEOUT="${HELM_TIMEOUT:-20m}"
ROLLOUT_TIMEOUT="${ROLLOUT_TIMEOUT:-420s}"
IMAGE_REPOSITORY="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"

say() { echo "=== $* ==="; }

python3 ci/deploy/oan_chart.py require-deployable registry dev
HELM_RELEASE="$(python3 ci/deploy/oan_chart.py release registry)"
HELM_NAMESPACE="$(python3 ci/deploy/oan_chart.py namespace registry)"
NS=(-n "$HELM_NAMESPACE")

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

say "Verified central chart"
CHART_ARCHIVE="$(python3 ci/deploy/oan_chart.py fetch registry "$WORK/chart")"
CENTRAL_VALUES="$(python3 ci/deploy/oan_chart.py values registry "$WORK/public-values.yaml")"
echo "chart:     $(python3 ci/deploy/oan_chart.py version registry) (platform $(python3 ci/deploy/oan_chart.py platform registry))"
echo "release:   ${HELM_RELEASE}"
echo "namespace: ${HELM_NAMESPACE}"
echo "images:    ${IMAGE_REPOSITORY}:<component>-${TAG}"

say "Release check"
# Upgrade only. A missing release is an error, never a first install.
if ! helm status "$HELM_RELEASE" "${NS[@]}" -o json > "$WORK/status.json" 2> "$WORK/status.err"; then
  echo "ERROR: release ${HELM_RELEASE} was not found in namespace ${HELM_NAMESPACE} (or the account cannot read it):" >&2
  tail -3 "$WORK/status.err" >&2
  echo "  This deploy only upgrades an existing release; it never installs one." >&2
  exit 1
fi
STATUS="$(sed -n 's/.*"status":"\([a-z-]*\)".*/\1/p' "$WORK/status.json" | head -1)"
echo "status:    ${STATUS:-unknown}"
case "$STATUS" in
  pending-*)
    echo "ERROR: release ${HELM_RELEASE} is '${STATUS}' from an interrupted deploy." >&2
    echo "  Inspect: helm -n ${HELM_NAMESPACE} history ${HELM_RELEASE}" >&2
    exit 1 ;;
esac

# The pinned public values leave the images and the enabled flags out on purpose:
# this build owns them. Every workload this build produces is switched on here.
cat > "$WORK/ci-values.yaml" <<EOF2
registry:
  staffApi:
    enabled: true
    image: {repository: '${IMAGE_REPOSITORY}', tag: 'staff-api-${TAG}'}
  partnerApi:
    enabled: true
    image: {repository: '${IMAGE_REPOSITORY}', tag: 'partner-api-${TAG}'}
  celeryWorker:
    enabled: true
    image: {repository: '${IMAGE_REPOSITORY}', tag: 'celery-${TAG}'}
  celeryBeat:
    enabled: true
    image: {repository: '${IMAGE_REPOSITORY}', tag: 'celery-${TAG}'}
  staffUi:
    enabled: true
    image: {repository: '${IMAGE_REPOSITORY}', tag: 'staff-ui-${TAG}'}
  dbSeed:
    enabled: true
    image: {repository: '${IMAGE_REPOSITORY}', tag: 'db-seed-${TAG}'}
EOF2
VALUES=(-f "$CENTRAL_VALUES" -f "$WORK/ci-values.yaml")

say "Render"
# A chart or values mistake fails here, before anything is changed. The rendered
# manifests are kept for the build's artifacts.
helm template "$HELM_RELEASE" "$CHART_ARCHIVE" "${NS[@]}" "${VALUES[@]}" > "$WORK/rendered.yaml"
echo "rendered $(wc -l < "$WORK/rendered.yaml") lines of manifests"
cp "$WORK/rendered.yaml" "dev-rendered-${BUILD_NUMBER:-manual}.yaml"
helm get values "$HELM_RELEASE" "${NS[@]}" -a -o yaml > "dev-values-before-${BUILD_NUMBER:-manual}.yaml"

# Revision to go back to: the last one Helm recorded as `deployed` before this build.
PREV="$(helm history "$HELM_RELEASE" "${NS[@]}" -o json 2>/dev/null | python3 -c '
import json, sys
try:
    rows = json.load(sys.stdin)
except ValueError:
    rows = []
done = [r["revision"] for r in rows if r.get("status") == "deployed"]
print(done[-1] if done else "")
')"
if [ -n "$PREV" ]; then echo "rollback target: revision ${PREV}"; else echo "rollback target: none (no deployed revision found)"; fi

# Save what an operator needs, then put the release back and fail the build.
fail_and_rollback() {
  local why="$1" report="deploy-failure-${BUILD_NUMBER:-manual}.txt"
  say "FAILED: ${why}" >&2
  {
    echo "== failure: ${why}"
    echo "== helm history"; helm history "$HELM_RELEASE" "${NS[@]}" --max 6 || true
    echo "== pods"; kubectl get pods "${NS[@]}" -l "app.kubernetes.io/instance=${HELM_RELEASE}" -o wide || true
    echo "== pods not Running/Succeeded"; kubectl get pods "${NS[@]}" --field-selector=status.phase!=Running,status.phase!=Succeeded || true
    echo "== warning events"; kubectl get events "${NS[@]}" --field-selector type=Warning --sort-by=.lastTimestamp | tail -40 || true
    for D in staff-portal-api staff-portal-ui partner-api; do
      echo "== logs ${HELM_RELEASE}-${D}"
      kubectl logs "deploy/${HELM_RELEASE}-${D}" "${NS[@]}" --all-containers --prefix --tail=60 2>&1 || true
    done
    echo "== jobs"; kubectl get jobs "${NS[@]}" || true
  } > "$report" 2>&1 || true
  echo "diagnostics saved to ${report}" >&2
  if [ -n "$PREV" ]; then
    say "rolling back ${HELM_RELEASE} to revision ${PREV}" >&2
    if helm rollback "$HELM_RELEASE" "$PREV" "${NS[@]}" --wait --timeout "$HELM_TIMEOUT"; then
      say "rolled back to revision ${PREV}; the previous release is running again" >&2
    else
      say "ROLLBACK FAILED: the release needs attention: helm -n ${HELM_NAMESPACE} history ${HELM_RELEASE}" >&2
    fi
  else
    say "no earlier deployed revision to roll back to" >&2
  fi
  exit 1
}

say "helm upgrade started $(date -u +%H:%M:%S) UTC (timeout ${HELM_TIMEOUT})"
# No --install, no --atomic: on failure fail_and_rollback saves diagnostics first, then
# rolls back, so the evidence is kept (a plain --atomic would delete it with the pods).
if ! helm upgrade "$HELM_RELEASE" "$CHART_ARCHIVE" "${NS[@]}" \
      --reset-values "${VALUES[@]}" --cleanup-on-fail --timeout "$HELM_TIMEOUT"; then
  fail_and_rollback "helm upgrade did not complete"
fi
say "helm upgrade finished $(date -u +%H:%M:%S) UTC"

say "Rollout"
for D in staff-portal-api staff-portal-ui partner-api; do
  if ! kubectl rollout status "deployment/${HELM_RELEASE}-${D}" "${NS[@]}" --timeout="$ROLLOUT_TIMEOUT"; then
    fail_and_rollback "${HELM_RELEASE}-${D} did not roll out within ${ROLLOUT_TIMEOUT}"
  fi
done

say "Deployed ${TAG} to ${HELM_NAMESPACE}"
kubectl get deploy "${NS[@]}" -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,IMAGE:.spec.template.spec.containers[0].image \
  | grep -E "^NAME|^${HELM_RELEASE}-" || true
