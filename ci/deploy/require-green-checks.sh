#!/usr/bin/env bash
# Refuse to deploy a commit whose GitHub checks are not all green.
#
#   ci/deploy/require-green-checks.sh <owner/repo> <commit sha>
#
# checks.yml runs on every push, so the exact commit a pipeline deploys carries its own check runs. This reads them and
# the commit's combined status through the GitHub API:
#   green   every check run completed as success, neutral or skipped, and no status failed  -> exit 0
#   failed  any check run failed, was cancelled or timed out, or a status failed           -> exit 1 at once
#   pending a check run still queued or running, or none reported yet                       -> wait and read again
# Pending is read again every POLL_SECONDS (30) until WAIT_MINUTES (30) have passed; then the build stops. Blank or
# pending never deploys. Branch protection cannot be used, so this is what keeps a red merge off the clusters.
#
# GH_TOKEN (optional) lifts the API rate limit; it is sent only to api.github.com and never printed.
set -euo pipefail
repo=${1:?usage: require-green-checks.sh <owner/repo> <sha>}
sha=${2:?usage: require-green-checks.sh <owner/repo> <sha>}
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "not a full commit sha: $sha" >&2; exit 2; }
api=${GITHUB_API_URL:-https://api.github.com}
deadline=$(( $(date +%s) + ${WAIT_MINUTES:-30} * 60 ))
headers=(-H 'Accept: application/vnd.github+json')
if [ -n "${GH_TOKEN:-}" ]; then headers+=(-H "Authorization: Bearer $GH_TOKEN"); fi
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

while :; do
  # Files, not arguments: a check-runs answer can exceed the 128 KB limit of one argument.
  curl -fsS "${headers[@]}" -o "$work/runs.json" "$api/repos/$repo/commits/$sha/check-runs?per_page=100"
  curl -fsS "${headers[@]}" -o "$work/status.json" "$api/repos/$repo/commits/$sha/status"
  verdict=$(python3 -c '
import json, sys
runs = json.load(open(sys.argv[1], encoding="utf-8")).get("check_runs", [])
statuses = json.load(open(sys.argv[2], encoding="utf-8")).get("statuses", [])
ok = {"success", "neutral", "skipped"}
failed = [r["name"] + "=" + str(r.get("conclusion")) for r in runs
          if r.get("status") == "completed" and r.get("conclusion") not in ok]
failed += [s["context"] + "=" + s["state"] for s in statuses if s.get("state") in ("failure", "error")]
pending = [r["name"] for r in runs if r.get("status") != "completed"]
pending += [s["context"] for s in statuses if s.get("state") == "pending"]
if failed:
    print("failed", ", ".join(sorted(failed)))
elif pending or not runs:
    print("pending", ", ".join(sorted(pending)) or "no check runs reported yet")
else:
    print("green", len(runs), "check run(s):", ", ".join(sorted(r["name"] for r in runs)))
' "$work/runs.json" "$work/status.json")
  case "$verdict" in
    green*) echo "checks of $repo@${sha:0:12}: ${verdict}"; exit 0 ;;
    failed*) echo "checks of $repo@${sha:0:12} are not green: ${verdict#failed }; nothing is deployed." >&2; exit 1 ;;
  esac
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "checks of $repo@${sha:0:12} still pending after ${WAIT_MINUTES:-30} min (${verdict#pending }); nothing is deployed." >&2
    exit 1
  fi
  echo "waiting for checks of $repo@${sha:0:12}: ${verdict#pending }"
  sleep "${POLL_SECONDS:-30}"
done
