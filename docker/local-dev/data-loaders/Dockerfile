# LOCAL DEVELOPMENT ONLY. Not built by the Jenkinsfile and not part of any
# deployable image.
#
# Loads reference and sample data into the local compose stack: the code lists
# into the local Master Data database and the sample Development Agents into
# the register. On a cluster this is done by the Master Data db-seed image and
# by openg2p-data; the loaders here are the copies that are to move to
# openg2p-data (docs/refactor/moves-to-openg2p-data/README.md).
#
# The data is a clone of the COSS openg2p-data fork made at build time (use
# OPENG2P_DATA_REF to pick a branch), or a local checkout mounted by
# OPENG2P_DATA_PATH (see docker-compose.yml).
ARG RP_VERSION=1.2.2-rc.557
FROM openg2p/openg2p-registry-db-seed:${RP_VERSION}
ARG OPENG2P_DATA_REPO=https://github.com/Centre-for-Open-Societal-Systems/openg2p-data.git
ARG OPENG2P_DATA_REF=develop
RUN rm -rf /openg2p-data \
 && git clone --quiet --depth 1 --branch "${OPENG2P_DATA_REF}" "${OPENG2P_DATA_REPO}" /openg2p-data \
 && rm -rf /openg2p-data/.git
COPY docs/refactor/moves-to-openg2p-data/load_sample_data.py /local/load_sample_data.py
COPY docs/refactor/moves-to-openg2p-data/load_codelists_mdm.py /local/load_codelists_mdm.py
