#!/usr/bin/env bash
# The offline checks GitHub (checks.yml) and Jenkins (dev.groovy, stage 'Check deploy script') both run: no network,
# no cluster, no cloud credentials. Run from the repository root.
set -euo pipefail
# The rules are in ruff.toml.
python -m ruff check --no-cache .
# Every test in test/, so a new test file runs without being listed here. test/sanity is an overlay on the platform's
# sanity image and runs against a deployment. da-extension/tests import the platform, so they run in the staff-api
# image (checks.yml).
python -m pytest -q -p no:cacheprovider test --ignore=test/sanity
find ci scripts -type f -name '*.sh' -print0 | xargs -0 -r -n1 bash -n
