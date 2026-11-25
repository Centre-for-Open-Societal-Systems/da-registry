# Release

How a DA Registry version is numbered, built and promoted. Where each version goes is in
[deployment](deployment.md).

## Versions

| What | Where it is set | Example |
| --- | --- | --- |
| Repository version | `version` in [`init.yaml`](../init.yaml) | `1.0.0` |
| Build version: image tag | `<version>-<branch>.<BUILD_NUMBER>` ([`ci/image_names.py`](../ci/image_names.py)) | `1.0.0-develop.90` |
| Chart version | set by oan-helm `scripts/ci/package_chart.py` when the build packages the chart; `helm/openg2p-da-registry/Chart.yaml` keeps `version: 0.0.0` | |
| Staging version | the rc of a develop build, added by the staging promotion | |
| OpenG2P platform (`rpVersion`) | `appVersion` and the `openg2p-registry` dependency in `helm/openg2p-da-registry/Chart.yaml`, `ARG RP_VERSION` in every Dockerfile, `RP_VERSION` in `ci/pipelines/dev.groovy`, and `platformVersion` in `ci/deploy/oan-chart.json` | `1.2.2-rc.614` |
| DA extension package | `__version__` in `da-extension/src/openg2p_registry_da_extension/__init__.py` | `1.0.3` |

All six images are built on the platform, so each carries `-<rpVersion>` in its repository name and a platform bump
starts new ECR repositories: `eoan/da-registry/staff-api-1.2.2-rc.614:1.0.0-develop.90`. ECR tags are immutable, so a
version is pushed once and there is no moving tag. `ci/ecr_repository.py` creates a missing repository with the
standard settings. The naming follows oan-helm `docs/release/naming-standard.md`, section 6.

## Release flow

1. **Merge to `develop`.** The build validates, publishes the images and deploys them to New Dev. It then publishes
   the packaged chart to oan-helm `repository/develop/`, where oan-helm's workflow updates the index, changelog and
   rollback history. If publishing fails the build is UNSTABLE: New Dev already runs it.
2. **Merge `develop` into `staging`.** The staging build promotes the chart develop built from the same tree. It adds
   the rc tag to the same image digests, deploys to staging and publishes the rc chart. Nothing is rebuilt.
3. **Production.** Not defined yet ([deployment](deployment.md#production)).

Before step 2, add the changes to [CHANGELOG.md](../CHANGELOG.md) under a heading for the version being promoted.

## Changing the platform version

The platform version is owned centrally: an oan-helm release of the chart moves first. Then:

1. `python3 ci/deploy/bump_pin.py <oan-helm commit> --write` moves the pin in `ci/deploy/oan-chart.json`, the
   expected version in `test/test_oan_chart.py` and, for a new platform version, `RP_VERSION` in
   `ci/pipelines/dev.groovy` and every Dockerfile ([`ci/deploy/README.md`](../ci/deploy/README.md)).
2. Move `appVersion` and the `openg2p-registry` dependency version in `helm/openg2p-da-registry/Chart.yaml` by hand:
   `bump_pin.py` does not.
3. Check the upstream staff-ui source revision in `ui/staff-ui/deps.json`, which pins a commit, not a version.

`scripts/bump-rp-version.sh` is out of date: it looks for `0.0.0-develop.N` platform versions and edits only the
Dockerfiles. Do not use it for an rc version.

These tests fail when the copies disagree:

- `test/test_rp_pin_lockstep.py`: `oan-chart.json` against the Dockerfiles, `dev.groovy` and `Chart.yaml`;
- `test/test_image_names.py`: the Dockerfiles against the chart's `appVersion`;
- `test/test_oan_chart.py`: the pin and the archive it names.

## Rollback

What the pipelines do today:

- New Dev: a failed upgrade or rollout is rolled back to the last `deployed` revision after the diagnostics are saved.
- Staging: a failed upgrade is rolled back to the last deployed Helm revision.
- A Helm rollback restores the chart and values, not data that hooks or users wrote.
- Data is restored only from a backup, and no pipeline takes one yet. See
  [rollback and recovery](deployment.md#rollback-and-recovery).

The rollback policy is still to be agreed: when a release is rolled back instead of fixed forward, who decides, and
how a database change is undone.
