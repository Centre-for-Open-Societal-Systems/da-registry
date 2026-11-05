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

**Automatic proposal:** the last stage of every successful `develop` build ("Propose chart pin update") runs
`ci/deploy/propose_pin_pr.py`. It compares the pin with the head of oan-helm `main` (the newest released chart and its current
public values, which change in their own PRs, without a chart release). When the chart version or the values digest differs it
writes the new pin on a branch, runs the pin tests and a verified prefetch of the chart and values, pushes the branch and opens a
pull request to `develop` titled `Pin OAN chart: ...`. It never proposes a downgrade and stops if a published archive's digest
ever changes. The PR also moves the files that must agree with the pin (the expected version in `test/test_oan_chart.py`, and for a
new platform version `RP_VERSION` in the Jenkinsfile and the Dockerfiles). A person reviews and merges it; the merge is what
deploys. The stage never deploys and never fails the build: with no credential, or if GitHub refuses, it turns UNSTABLE and says
why. It needs the Jenkins credential `oan-ci-app` (a GitHub App, or "Username with password") with Contents and Pull requests
write on this repository. Because it runs after builds, an oan-helm change is noticed at the next build; "Build Now" on `develop`
checks on demand.

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

## oan-helm image pull request (last stage)

The last stage, **Open oan-helm image PR** (`ci/deploy/release_images.py`), runs on `develop` only after the build, the
deploy (and its rollback, if one was needed) and the pin stage. It never fails the build and never deploys.

- **Digests.** Build & Push records the ECR digest of each image from the `docker push` output
  (`.build/image-digests.tsv`: `staff-api`, `partner-api`, `celery`, `staff-ui`, `db-seed`), so no extra AWS permission is
  needed.
- **What changes.** In `charts/openg2p-da-registry/values.yaml` of oan-helm, for `staffApi`, `partnerApi`, `celeryWorker`,
  `celeryBeat`, `staffUi` and `dbSeed`: `image.repository` (`<ECR registry>/openg2p/da-registry/<component>`) and `image.tag`
  (`<commit12>@sha256:<digest>`). Twelve lines; the `enabled` flags and everything else stay as they are.
  The chart carried empty images until now: `ci/deploy-dev.sh` sets the images (and `enabled: true`) of the build it
  deploys on top of the pinned chart, so what the chart records never decides what is deployed.
- **How.** The change goes on the branch `bot/da-registry-images-<commit12>` of the fork of oan-helm and a pull request
  is opened from it into `Centre-for-Open-Societal-Systems/oan-helm` `main` (the open one for the same commit is
  updated). The stage does not wait for the merge and is green once the pull request is open; with no token, or if
  GitHub refuses, it is UNSTABLE and says why. A person with write access merges it (checks `protected-paths` and
  `validate`); oan-helm's release workflow then publishes the next `openg2p-da-registry` version and writes the
  `CHANGELOG.md` entry, and the pin stage of a later build proposes moving the pin to it.
- **One pull request per commit.** A commit whose images oan-helm `main` already carries opens nothing (re-run, Replay,
  rebuild). The commit that merges a chart-pin pull request (only `ci/deploy/oan-chart.json` changed) opens nothing
  either: otherwise image pull request, release, pin pull request and the next build would follow each other forever.

Credential `oan-helm-fork-token` (Jenkins "Username with password", global): the username is the GitHub account that
owns the fork of oan-helm, the password a classic token of that account with the `public_repo` scope (a fine-grained
token cannot open a pull request on the org repository). The fork must exist. Check a token with
`curl -sI -H "Authorization: Bearer $TOKEN" https://api.github.com/user | grep -i x-oauth-scopes`.

`DRY_RUN=1 IMAGE_TAG=<commit12> ECR_REGISTRY=<registry> python3 ci/deploy/release_images.py` (with
`.build/image-digests.tsv`) prints the tags it would write and changes nothing.

Tests (no network or cluster): `python3 -m unittest discover -s test -p test_deploy_ci.py -v`; the Jenkinsfile runs
them in the "Check deploy script" stage.
