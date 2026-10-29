# Native registry seeding with DA metadata layered on top.
ARG RP_VERSION=1.2.2-rc.557
FROM openg2p/openg2p-registry-db-seed:${RP_VERSION}

# All sample and reference data comes from the COSS fork of openg2p-data
# (country pack ETH-OAN: geography, code lists, sample people, sample DAs).
# The base image bakes upstream OpenG2P's copy at /openg2p-data; replace it
# with the fork at the ref the deployment pins. OPENG2P_DATA_DIR in the
# entrypoint and the loaders still points at /openg2p-data.
ARG OPENG2P_DATA_REPO=https://github.com/Centre-for-Open-Societal-Systems/openg2p-data.git
ARG OPENG2P_DATA_REF=develop
RUN rm -rf /openg2p-data \
 && git clone --quiet --depth 1 --branch "${OPENG2P_DATA_REF}" "${OPENG2P_DATA_REPO}" /openg2p-data \
 && rm -rf /openg2p-data/.git

RUN rm -rf /seed/meta_data/* /seed/awe_meta_data/* /seed/templates/* /seed/seed-data/*

COPY da-extension/src/openg2p_registry_da_extension/meta_data/ /seed/meta_data/
COPY da-extension/src/openg2p_registry_da_extension/awe_meta_data/ /seed/awe_meta_data/
COPY da-extension/src/openg2p_registry_da_extension/templates/ /seed/templates/
COPY docker/db-seed/seed-data/ /seed/seed-data/
# The DA variant's loaders (the platform entrypoint owns the LOAD_SAMPLE_DATA
# hook; this image supplies what it runs). load_codelists_mdm.py is for the
# local compose stack only, see the file.
COPY docker/db-seed/load_sample_data.py /seed/load_sample_data.py
COPY docker/db-seed/load_codelists_mdm.py /seed/load_codelists_mdm.py

RUN chmod +x /seed/load_sample_data.py /seed/load_codelists_mdm.py
