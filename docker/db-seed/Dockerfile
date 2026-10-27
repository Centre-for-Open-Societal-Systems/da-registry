# Native registry seeding with DA metadata layered on top.
ARG RP_VERSION=1.2.2-rc.557
FROM openg2p/openg2p-registry-db-seed:${RP_VERSION}

RUN rm -rf /seed/meta_data/* /seed/awe_meta_data/* /seed/templates/* /seed/seed-data/*

COPY da-extension/src/openg2p_registry_da_extension/meta_data/ /seed/meta_data/
COPY da-extension/src/openg2p_registry_da_extension/awe_meta_data/ /seed/awe_meta_data/
COPY da-extension/src/openg2p_registry_da_extension/templates/ /seed/templates/
COPY docker/db-seed/seed-data/ /seed/seed-data/
COPY docker/db-seed/load_sample_data.py /seed/load_sample_data.py

RUN chmod +x /seed/load_sample_data.py
