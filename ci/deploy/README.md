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

A develop build no longer installs the pinned chart: see "Chart delivery" below. The pin is the fallback for a deploy by hand, and
its public values are still what every deploy uses. Move it with `ci/deploy/bump_pin.py`.

**By hand:** `python3 ci/deploy/bump_pin.py <40-hex oan-helm commit>` does steps 2 to 5 below (it also reads the
chart version from `releases/current.yaml` at that commit, or take `--version`). It cross-checks the archive against
`repository/SHA256SUMS` at that commit and prints old -> new; add `--write` to update `oan-chart.json`, then run
step 6 and open the pull request. With `--write` it also moves the expected version in `test/test_oan_chart.py` and, when
the platform version changes, `RP_VERSION` in the Jenkinsfile and the Dockerfiles. A build never moves the pin.

1. Merge the oan-helm change; its release workflow publishes the chart and commits it to
   `repository/` on `main`. Note a commit on `main` that contains the archive and the
   `repository/index.yaml` entry for the version, and the public values you want (the values
   file changes in its own PRs, so the commit that published the archive may have older values).
2. `repository` and `values.url`: replace the 40-hex commit with that commit. They must name the same commit.
3. `version`: the released chart version.
4. `sha256`: `sha256sum openg2p-da-registry-<version>.tgz` of the archive at that commit.
5. `values.sha256`: `sha256sum environments/dev/values/da.yaml` at that commit.
6. Run `python3 -m unittest discover -s test -p test_oan_chart.py` and
   `python3 ci/deploy/oan_chart.py prefetch registry`, which downloads and verifies both files.

While the commit and the two SHA-256 values are all zeros, every chart operation fails with
"still a placeholder", so a deploy cannot start from an unfinished pin.

## Deploy

`ci/deploy-dev.sh <12-char-commit>` (run by the Jenkinsfile's "Deploy to Development" stage on
every `develop` build) downloads and verifies the archive and values, requires the
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

## Rollback

If `helm upgrade` fails or one of the three application Deployments does not roll out, `ci/deploy-dev.sh` first writes
`deploy-failure-<build>.txt` (release history, pods, warning events, logs, jobs; Jenkins archives it), then runs
`helm rollback` to the last revision that was `deployed` before the build, and fails the build. It does not use
`--atomic`, so the evidence is saved before the pods are removed. A rollback restores the chart and values only: it
cannot undo database changes made by an init or db-seed hook. If the release has no earlier `deployed` revision, the
build fails with no rollback.

## Chart delivery

A develop build packages `helm/openg2p-da-registry` with its images (stage `Package chart`, `ci/deploy/package-chart.sh`, using
`scripts/ci/package_chart.py` of oan-helm). The version comes from git: `0.0.0-develop.<commit count>`. `ci/deploy-dev.sh` installs
that archive. After a successful deploy, stage `Publish chart` (`ci/deploy/publish-chart.sh`) adds the same file to
`repository/develop/` of oan-helm, whose workflow updates the index, changelog and rollback history. If publishing fails the stage
and the build are UNSTABLE; New Dev already runs the build. It uses the Jenkins credential `oan-helm-fork-token`, a maintainer's
token for now. Rollback is described in `docs/rollback.md` of oan-helm.

Tests (no network or cluster): `python3 -m unittest discover -s test -p test_deploy_ci.py -v`; the Jenkinsfile runs
them in the "Check deploy script" stage.
