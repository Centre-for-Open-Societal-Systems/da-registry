#!/usr/bin/env bash
# Package helm/openg2p-da-registry with this build's images into built-chart/, with
# scripts/ci/package_chart.py of oan-helm. The deploy installs that archive and publish-chart.sh
# publishes the same file. .build/image-digests.tsv comes from the stage Build & Push.
set -euo pipefail
: "${BRANCH_NAME:?Jenkins sets the branch}"
: "${ECR_REGISTRY:?Missing ECR registry}"
: "${ECR_BASE:?Missing ECR base}"
: "${IMAGE_TAG:?Missing image tag}"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

while IFS=$'\t' read -r component digest; do
  case "$component" in
    staff-api) paths=registry.staffApi.image ;;
    staff-ui) paths=registry.staffUi.image ;;
    partner-api) paths=registry.partnerApi.image ;;
    celery) paths='registry.celeryWorker.image registry.celeryBeat.image' ;;
    db-seed) paths=registry.dbSeed.image ;;
    *) echo "No chart image for $component" >&2; exit 1 ;;
  esac
  for path in $paths; do
    printf '%s\t%s\t%s@%s\n' "$path" "$ECR_REGISTRY/$ECR_BASE/$component" "$IMAGE_TAG" "$digest"
  done
done < .build/image-digests.tsv > "$WORK/images.tsv"

git clone --quiet --depth 1 --filter=blob:none --sparse \
  https://github.com/Centre-for-Open-Societal-Systems/oan-helm.git "$WORK/oan-helm"
git -C "$WORK/oan-helm" sparse-checkout set scripts/ci
python3 "$WORK/oan-helm/scripts/ci/package_chart.py" \
  --chart helm/openg2p-da-registry --images "$WORK/images.tsv" --output built-chart \
  --source-repository Centre-for-Open-Societal-Systems/da-registry \
  --source-commit "$(git rev-parse HEAD)" --subject "$(git log -1 --pretty=%s)" \
  --release da-registry --namespace da-registry \
  --overlay environments/dev/values/da.yaml --branch "$BRANCH_NAME"
