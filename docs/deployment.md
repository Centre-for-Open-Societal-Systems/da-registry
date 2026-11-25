# Deployment

How the DA Registry reaches each environment, and where the detailed procedures are. Each change goes through
Jenkins. Never run `helm` or `psql` against an environment by hand.

## What is deployed

| Release | Namespace | What it is |
| --- | --- | --- |
| `da-registry` | `da-registry` | The chart `helm/openg2p-da-registry`, which wraps the OpenG2P `openg2p-registry` chart at the platform version in its `appVersion`. It runs the six platform images built here: staff-api, staff-ui, partner-api, celery (worker and beat), db-seed and sanity-tests. It also carries the [reporting views](#reporting-views) and the sample-approver password hook. |

DA builds no connector and no dashboard images ([`ci/image_names.py`](../ci/image_names.py)). The chart still has
`dashboardApi` and `dashboardUi` templates, off by default. Image names follow `ci/image_names.py`. The shared Commons
services (Keycloak, AWE, Master Data, MinIO, PostgreSQL) are separate releases with their own delivery.

On install and on every upgrade, the post-install hooks replay the seed (`meta_data/`, `awe_meta_data/`), re-apply
the reporting views when they are on, and run the sanity smoke tests (`test/sanity`). The seed is written to be
replayed: every INSERT has ON CONFLICT (`test/test_seed_on_conflict.py`).

## Environments

| | Dev (New Dev) | Staging | Production |
| --- | --- | --- | --- |
| Source branch | `develop` | `staging` | not defined yet |
| Pipeline | [`ci/pipelines/dev.groovy`](../ci/pipelines/dev.groovy) | [`ci/pipelines/staging.groovy`](../ci/pipelines/staging.groovy) | not defined yet |
| Namespace, release | `da-registry`, `da-registry` | `da-registry`, `da-registry` | not defined yet |
| Registry UI | `https://da-registry.development.oanstaging.com` | `https://da-registry.qa.oanstaging.com` | not defined yet |
| Values | oan-helm `environments/dev/values/da.yaml` | oan-helm `environments/staging/values/da.yaml` | not defined yet |
| Chart installed | the chart the build packaged; [`oan-chart.json`](../ci/deploy/oan-chart.json) for a deploy run by hand | the rc of the chart develop built from the same tree | not defined yet |

### Dev

A develop build checks the chart pin, runs `ci/validate.sh`, builds and pushes the images, waits for every GitHub
check of the commit to be green, packages the chart with the images
([`ci/deploy/package-chart.sh`](../ci/deploy/package-chart.sh)) and upgrades the release with that chart
([`ci/deploy-dev.sh`](../ci/deploy-dev.sh)). It then publishes the chart to oan-helm `repository/develop/`
([`ci/deploy/publish-chart.sh`](../ci/deploy/publish-chart.sh)). Other branches and pull requests build and push the
images and stop there. The details, and a deploy by hand from the pin, are in [`ci/deploy/README.md`](../ci/deploy/README.md).

`ci/deploy-dev.sh` only upgrades: it never installs, uninstalls or touches a database. It switches on every workload
the build produces and the reporting views, and, for dev only, the Keycloak accounts for approved people
([keycloak-users.md](keycloak-users.md)). Jenkins reaches the cluster as the ServiceAccount `da-registry-ci`, which
can act in namespace `da-registry` only ([`k8s/da-registry-newdev-rbac.yaml`](../k8s/da-registry-newdev-rbac.yaml)).

DA has no operator pipeline: there is no publish-only or fresh-install job. `scripts/uninstall-registry.sh` removes a
release and its databases by hand; it is not run by any pipeline.

### Staging

A merge into `staging` from `develop` builds nothing. After the green-checks gate, it promotes the chart develop built
from the same tree: the same image digests under an rc version, deployed with oan-helm `scripts/ci/deliver_staging.sh`
and the staging values. If develop never built the tree, the build fails, so staging only runs what New Dev ran
first. `LOAD_SAMPLE_DATA` (off by default) loads the sample records.

### Production

Not defined yet. Open questions, to be decided before this section is written:

- the cluster, namespace and the Commons endpoints production uses;
- the backup method and when it runs;
- the rollback policy (see [release](release.md#rollback)).

## Reporting views

Two materialized views flatten the register for reports, so a report never reads the `g2p_register_*` tables and a
schema change is absorbed in this repository. They are defined in
[`docker/db-seed/reporting_views.sql`](../docker/db-seed/reporting_views.sql), which ships in the db-seed image.

| View | One row per | Columns |
| --- | --- | --- |
| `da_rpt_da` | DA (`g2p_register_das`) | DA-ID, record status, gender, position and specialisation (code and label), joining date, the DA-ID they report to, source, registration and last-approval dates, region/zone/woreda/kebele codes and names |
| `da_rpt_da_qualification` | education record (`g2p_register_qualifications`) | level (code and label) and passout year, with the DA's record status, position, specialisation and location carried down from `da_rpt_da` |

- **No personal data.** Only the DA-ID and the reports-to DA-ID: no names, Fayda ID, phone numbers, e-mail or dates of
  birth.
- **Every record status** is kept; a report filters on `record_status`.
- **Location.** The codes come from the record's code columns, or from `geo_code_hierarchy_json` for a record approved
  before those columns were filled.
- **Labels** come from `g2p_attribute_values` where the platform still has it; otherwise the label falls back to the
  stored code.

**How they run.** The hook `templates/reporting-views.yaml` applies the file on every install and upgrade, after
waiting for the register tables and columns the staff-api migrations create. The CronJob
`templates/reporting-views-refresh.yaml` refreshes them in dependency order (`da_rpt_da` first, `CONCURRENTLY` so reports keep reading the old rows), every 30 minutes by default
(`reporting.views.refreshSchedule`), and logs each run to `reporting_refresh_log` (kept 90 days). Both run in the
db-seed image. They are off in the chart (`reporting.views.enabled: false`) and switched on by the dev deploy. The
oan-helm staging values do not set `reporting.views.enabled`, so staging appears to run without them; to be confirmed.

**How they are tested** (in `ci/validate.sh`, no database):

- `test/test_db_seed_reporting_views.py`: the image carries the file after the seed cleanup, the file can be re-applied,
  views drop in dependency order, no personal data is carried, the hook waits for every table and column the views
  read, the legacy label table is optional, the refresh job matches the views, and they are off by default and on in
  the dev deploy.
- `test/test_metadata_consistency.py`: every column the views read is a column of the DA or Qualification model.

They have not been run against PostgreSQL 16 in CI.

## Gates before a deploy

- Every GitHub check of the commit is green ([`ci/deploy/require-green-checks.sh`](../ci/deploy/require-green-checks.sh)),
  for both dev and staging. This includes `ci/validate.sh`, the extension tests and the chart lint and render
  ([ci/README.md](../ci/README.md)).
- The chart pin is checked on every build (`test/test_oan_chart.py`). A deploy by hand installs only the chart archive
  and values pinned in `oan-chart.json`, checked by SHA-256 (`ci/deploy/oan_chart.py`).
- The public values must list the object store host in the staff UI's image CSP, or reading them fails
  ([`ci/deploy/README.md`](../ci/deploy/README.md)).

## Rollback and recovery

- Dev: if the upgrade fails or one of the three application Deployments does not roll out, `ci/deploy-dev.sh` saves
  `deploy-failure-<build>.txt` (history, pods, events, logs, jobs; Jenkins archives it), rolls Helm back to the last
  `deployed` revision and fails the build. It does not use `--atomic`, so the evidence is kept. A release left
  `pending-*` by an interrupted run stops the deploy before anything changes.
- Staging: if the upgrade fails on a release that had a deployed revision, `deliver_staging.sh` rolls Helm back to
  it.
- A Helm rollback restores the chart and values, not data that hooks or users wrote. Data is restored only from a
  backup, and no pipeline takes one yet.
