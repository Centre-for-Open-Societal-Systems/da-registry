# Pinned central chart for the dev deploy

The DA registry deploys the chart `openg2p-da-registry` and its public dev values from
oan-helm, both pinned to one immutable oan-helm commit in `oan-chart.json` and verified by
SHA-256 before Helm sees them. There is no local chart source, no dependency update, no
moving branch URL and no `--reuse-values`.

`oan-chart.json` (role `registry`) records:

| Field | Meaning |
|---|---|
| `repository` | `https://raw.githubusercontent.com/Centre-for-Open-Societal-Systems/oan-helm/<release commit>/repository/` |
| `name`, `version` | chart `openg2p-da-registry` and its release version |
| `sha256` | SHA-256 of the chart archive `openg2p-da-registry-<version>.tgz` |
| `values.path`, `values.sha256`, `values.url` | public values `environments/dev/values/da.yaml` at the same commit, its SHA-256 and its URL (the URL must be the file at the `repository` commit) |
| `release`, `namespace` | the existing release `da-registry` in namespace `da-registry` |
| `platformVersion` | registry-platform version of the chart's `openg2p-registry` dependency; must equal the images' `RP_VERSION` |

## Moving the pin to a new oan-helm release

1. Merge the oan-helm change; its release workflow publishes the chart and commits it to
   `repository/` on `main`. Note that commit (the one that contains the archive and the
   `repository/index.yaml` entry for the version).
2. `repository` and `values.url`: replace the 40-hex commit with that commit. They must name the same commit.
3. `version`: the released chart version.
4. `sha256`: `sha256sum openg2p-da-registry-<version>.tgz` of the archive at that commit.
5. `values.sha256`: `sha256sum environments/dev/values/da.yaml` at that commit.
6. Run `python3 -m unittest discover -s test -p test_oan_chart.py` and
   `python3 ci/deploy/oan_chart.py prefetch registry`, which downloads and verifies both files.

While the commit and the two SHA-256 values are all zeros, every chart operation fails with
"still a placeholder", so a deploy cannot start from an unfinished pin.

## Deploy

`ci/deploy-dev.sh <12-char-commit>` (run by the Jenkinsfile's "Deploy to Development" stage when
`DEPLOY_TO_DEV` is ticked on `develop`) downloads and verifies the archive and values, requires the
release to exist, renders the manifests, and runs `helm upgrade --reset-values` with the pinned
values and this build's six images (`staff-api`, `partner-api`, `celery` for worker and beat,
`staff-ui`, `db-seed`, each with `enabled: true`) on top. It never installs, never uninstalls and
never touches a database.

Read-only verification: `python3 ci/deploy/oan_chart.py fetch registry <directory>` and
`python3 ci/deploy/oan_chart.py values registry <public-values.yaml>`.

The deploy node needs `python3`; PyYAML is vendored under `ci/deploy/vendor` (version in
`requirements.txt`) for an agent without it. Archives and values can be pre-downloaded into
`.central-charts/` (`oan_chart.py prefetch registry`); a corrupt cached archive fails closed with no
network fallback.
