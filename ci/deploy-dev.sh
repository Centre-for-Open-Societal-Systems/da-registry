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

say "helm upgrade started $(date -u +%H:%M:%S) UTC (timeout ${HELM_TIMEOUT})"
# No --install, no --atomic: a failing db-seed hook leaves the release inspectable
# instead of rolling it back.
if ! helm upgrade "$HELM_RELEASE" "$CHART_ARCHIVE" "${NS[@]}" \
      --reset-values "${VALUES[@]}" --cleanup-on-fail --timeout "$HELM_TIMEOUT"; then
  say "release history" >&2
  helm history "$HELM_RELEASE" "${NS[@]}" --max 5 >&2 || true
  say "recent warning events" >&2
  kubectl get events "${NS[@]}" --field-selector type=Warning --sort-by=.lastTimestamp 2>/dev/null | tail -20 >&2 || true
  exit 1
fi
say "helm upgrade finished $(date -u +%H:%M:%S) UTC"

say "Rollout"
for D in staff-portal-api staff-portal-ui partner-api; do
  if ! kubectl rollout status "deployment/${HELM_RELEASE}-${D}" "${NS[@]}" --timeout="$ROLLOUT_TIMEOUT"; then
    echo "ERROR: ${HELM_RELEASE}-${D} did not roll out within ${ROLLOUT_TIMEOUT}." >&2
    kubectl get pods "${NS[@]}" -l "app.kubernetes.io/instance=${HELM_RELEASE}" -o wide >&2 || true
    kubectl logs "deploy/${HELM_RELEASE}-${D}" "${NS[@]}" --all-containers --prefix --tail=60 >&2 || true
    exit 1
  fi
done

say "Deployed ${TAG} to ${HELM_NAMESPACE}"
kubectl get deploy "${NS[@]}" -o custom-columns=NAME:.metadata.name,READY:.status.readyReplicas,IMAGE:.spec.template.spec.containers[0].image \
  | grep -E "^NAME|^${HELM_RELEASE}-" || true
