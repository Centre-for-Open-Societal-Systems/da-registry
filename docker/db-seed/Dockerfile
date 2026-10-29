# Native registry seeding with the DA extension's configuration.
#
# The image is the platform's db-seed with the DA extension's metadata, AWE
# policies and templates in place of the reference extension's, and nothing
# else: no loaders, no generators, no sample data, no cloned data repository.
# All data (geography, code lists, sample people and DAs) lives in
# openg2p-data. The native entrypoint applies the whole tree (meta_data,
# awe_meta_data, templates).
ARG RP_VERSION=1.2.2-rc.557
FROM openg2p/openg2p-registry-db-seed:${RP_VERSION}
RUN rm -rf /seed/meta_data/* /seed/awe_meta_data/* /seed/templates/* /seed/seed-data/*
COPY da-extension/src/openg2p_registry_da_extension/meta_data/ /seed/meta_data/
COPY da-extension/src/openg2p_registry_da_extension/awe_meta_data/ /seed/awe_meta_data/
COPY da-extension/src/openg2p_registry_da_extension/templates/ /seed/templates/
ENTRYPOINT ["/seed/entrypoint.sh"]
