# CI

What checks a change to this repository, and where each check runs. Chart delivery and the pinned central chart are
in [deploy/README.md](deploy/README.md).

## Where checks run

| Runner | Trigger | What it runs |
| --- | --- | --- |
| GitHub Actions, [`checks.yml`](../.github/workflows/checks.yml) | every push and pull request | `contracts`: `ci/validate.sh`, then the DA extension tests (`da-extension/tests`) in the staff-api image built from `docker/staff-api/Dockerfile`, with a coverage report. `chart`: Helm dependency build, lint and render of `helm/openg2p-da-registry`. |
| Jenkins, [`Jenkinsfile`](../Jenkinsfile) | one multibranch job | `staging` branch: [`pipelines/staging.groovy`](pipelines/staging.groovy). Everything else, including pull requests: [`pipelines/dev.groovy`](pipelines/dev.groovy). |

`dev.groovy` checks the chart pin (`test/test_oan_chart.py` in the platform image) and runs `validate.sh` in
`python:3.11.14-slim` (stage `Check deploy script`) before it builds and pushes the six images. Only `develop` goes on
to package, deploy to New Dev and publish the chart. Neither `develop` nor `staging` deploys until every GitHub check
of the commit is green ([`deploy/require-green-checks.sh`](deploy/require-green-checks.sh)). Jenkins does not run the
extension tests itself: they are one of those GitHub checks. DA has no operator pipeline.

## validate.sh

The offline gate. It needs no cloud credentials or network, and Jenkins mounts the repository read-only. In order:

1. `ruff check .`, with the rules in [`ruff.toml`](../ruff.toml) (below).
2. `pytest test`, except `test/sanity`, an overlay on the platform's sanity image that runs against a deployment.
3. `bash -n` on every shell script under `ci/` and `scripts/`.

Run it locally from the repository root with Python 3.11 or 3.12 and the packages `checks.yml` installs:

```bash
pip install pytest==8.4.2 ruff==0.17.2 PyYAML==6.0.2 Jinja2==3.1.6
bash ci/validate.sh
```

### Lint

`ruff check .` covers every Python file of the repository except the vendored PyYAML (`deploy/vendor`). It enforces
only rules that find mistakes (pyflakes, comparisons to `None`/`True`, bare `except`, pylint errors), and only rules
the code passes today. Three pyflakes rules are not enforced yet: unused imports, f-strings without placeholders and
unused variables. `ruff.toml` lists them with their counts. Clearing one and removing it from `ignore` makes it
enforced.

### Guard tests

Some tests in `test/` guard contracts between files that nothing checks at runtime. A break there fails silently in a
deployment, so the test names what broke:

| Test | Guards |
| --- | --- |
| `test_rp_pin_lockstep.py` | The platform version in `deploy/oan-chart.json` equals every Dockerfile's `RP_VERSION`, `RP_VERSION` in `pipelines/dev.groovy`, and the chart's `appVersion` and `openg2p-registry` dependency. |
| `test_metadata_consistency.py` | Every field the widgets, register schemas, DCI and import templates and the `da_rpt_*` reporting views use is a column, and every dropdown list is in the pinned openg2p-data. |
| `test_seed_on_conflict.py` | Every INSERT in `meta_data/` and `awe_meta_data/` has ON CONFLICT, so the db-seed can replay. |
| `test_consent_scopes.py` | Every consent scope id named in the repository is a top-level key of the DCI search response. |
| `test_search_text.py` | `search_text` is built only from real columns, and raw register INSERTs write it. |
| `test_awe_policy_keys.py` | Registry approval bindings, AWE policies, stages and approver rules join on `policy_key`. |

Two known gaps are allowed by name in `test_metadata_consistency.py`, and the test fails once either is fixed, so
the entry is removed with the fix:

- `KNOWN_UNSTORED`: the import template writes `source` into each qualification row, and the Qualification register
  has no `source` column, so it is never stored.
- `KNOWN_NOT_IN_PACK`: the family Relationship list `DA_RELATIONSHIP` is not in openg2p-data at the commit db-seed
  pins. It is on openg2p-data develop.

The other tests cover the CI and deploy scripts: rollback and the pin updater (`test_deploy_ci.py`), the chart pin
(`test_oan_chart.py`), image names (`test_image_names.py`), ECR settings (`test_ecr_repository.py`), the green-checks
gate (`test_require_green_checks.py`), the reporting views in the db-seed image (`test_db_seed_reporting_views.py`),
the sample loader and the sample-approver password hook.

### Coverage

The extension tests on GitHub report line coverage of the installed extension (`openg2p_registry_da_extension`) and
enforce no minimum. A minimum is to be agreed. The baseline on 2026-11-25, on platform `1.2.2-rc.614`: **73%** of
3,020 statements (323 passed, 19 skipped).

`validate.sh` reports no coverage: the tests in `test/` read files and run scripts and import none of the extension.

## Folders

| Folder | Contents |
| --- | --- |
| `pipelines/` | The Jenkins pipelines the `Jenkinsfile` loads |
| `deploy/` | Chart packaging and publication, the pinned central chart, the green-checks gate |
| `deploy-dev.sh` | The New Dev deploy, with rollback on failure |
| `image_names.py`, `ecr_repository.py` | Image names and ECR repository settings |
| `validate.sh` | The offline gate above |
