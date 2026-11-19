# DA Registry sanity/e2e image: a thin extension of the platform suite.
#
# The registry platform publishes openg2p-registry-sanity-tests: the whole test
# harness (signing, DCI envelope building, PM/CM/Keycloak/AWE seeding, DB helpers,
# step logging, conftest banners), the register-independent tests (smoke and the
# fail-closed negative cases) and the entrypoint. All of that is inherited from
# the base image and runs unchanged here.
#
# This image overlays only the DA register's own parts:
#   - sanity/fixtures.py               the seeded DA and the DA register tables
#   - sanity/data_seed.py              injection into g2p_register_das
#   - tests/test_e2e_dci.py            DA DCI template (da_details) assertions
#   - tests/test_e2e_change_request.py DA register/history tables
#   - tests/test_smoke.py              the partner-api's DCI routes on this version
# They overwrite the reference registry's files at the same paths, so the
# inherited flow tests exercise the DA register. The register id, DCI reg type,
# search text, scopes and CR tab/section come from the chart (registry.sanity
# values), not from this image.
#
# RP_VERSION pins the base sanity image; keep it in lockstep with the other DA
# images and the openg2p-registry chart dependency.
#
# Build context = repo root.
ARG RP_VERSION=1.2.2-rc.614
FROM openg2p/openg2p-registry-sanity-tests:${RP_VERSION}

COPY test/sanity/sanity/fixtures.py                /app/sanity/fixtures.py
COPY test/sanity/sanity/data_seed.py               /app/sanity/data_seed.py
COPY test/sanity/tests/test_e2e_dci.py             /app/tests/test_e2e_dci.py
COPY test/sanity/tests/test_e2e_change_request.py  /app/tests/test_e2e_change_request.py
COPY test/sanity/tests/test_smoke.py               /app/tests/test_smoke.py
