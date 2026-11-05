#!/usr/bin/env bash
# Add the archive in built-chart/ to repository/<channel>/ of oan-helm, whose workflow updates the
# index, changelog and rollback history. Needs GH_TOKEN with push access to oan-helm.
set -euo pipefail
: "${GH_TOKEN:?Bind the oan-helm credential}"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
git clone --quiet --depth 1 --filter=blob:none --sparse \
  https://github.com/Centre-for-Open-Societal-Systems/oan-helm.git "$WORK/oan-helm"
git -C "$WORK/oan-helm" sparse-checkout set scripts/ci
status=0
python3 "$WORK/oan-helm/scripts/ci/publish_chart.py" built-chart/*.tgz || status=$?
if [ "$status" -eq 4 ]; then
  echo "This version was published by an earlier run of this commit."
  exit 0
fi
exit "$status"
