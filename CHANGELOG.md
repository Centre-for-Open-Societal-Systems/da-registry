# Changelog

Notable changes to the DA Registry, newest first, in the format of [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versions are the repository version in `init.yaml` (see [release](docs/release.md)). Before this file, the history is
the git log and the pull requests.

## [Unreleased]

### Added

- `ci/validate.sh` runs every test in `test/`, in GitHub and in Jenkins (#85).
- Guard tests for contracts between files that nothing checks at runtime (#86):
  - every field the widgets, schemas, templates and reporting views use is a column, and every dropdown list is in
    the pinned openg2p-data;
  - every seed INSERT has ON CONFLICT;
  - consent scope ids are releasable by the DCI search response;
  - `search_text` is built from real columns;
  - AWE policy keys join across the registry and AWE seeds;
  - every copy of the platform version follows the pin.
- A lint over every Python file with the rules in `ruff.toml`, and a coverage report of the extension tests, with no
  minimum yet. `ci/README.md`: where each check runs (#87).
- `docs/deployment.md`, including the reporting views, `docs/release.md` and this changelog.

### Known issues

- The import template writes `source` into each education record, and the Qualification register has no `source`
  column, so it is never stored.
- The family Relationship list `DA_RELATIONSHIP` is not in openg2p-data at the commit db-seed pins (`34b2394`), so the
  family Relationship field has no list to show. It is on openg2p-data develop.
- The local stack (`docker-compose.yml`, `docker/local-dev/data-loaders`) pins openg2p-data `dc7e7bf`, not the
  `34b2394` db-seed uses, so local dropdowns differ from the deployed ones.
- The sanity check's denied scope `qualifications` is never a key of the DCI response, so it cannot detect a leak.
- `scripts/bump-rp-version.sh` is out of date ([release](docs/release.md#changing-the-platform-version)).
