# syntax=docker/dockerfile:1

# DA Registry unified build definition (OpenG2P registry platform + DA extension).
#
# One Dockerfile with independent runtime targets, built through
# `docker compose build` or `docker build --target <target> ...`.
# Derived from the Farmer Registry build: the platform fixes are kept, the
# farmer-only customisations are not.

# Platform images from Docker Hub (openg2p/openg2p-registry-*), the same
# source the upstream farmer registry uses. Backend and staff UI come from one
# registry-platform pipeline run, so keep both on the same build number.
ARG RP_VERSION=1.2.2-rc.544
ARG STAFF_UI_VERSION=1.2.2-rc.544

# ---------------------------------------------------------------- staff API
FROM openg2p/openg2p-registry-staff-api:${RP_VERSION} AS staff-api

ENV REGISTRY_EXTENSION_MODULE=openg2p_registry_da_extension

COPY da-extension/ /app/da-extension/
RUN pip install --no-cache-dir /app/da-extension

# Fixes for bugs the pinned platform ships (async/await mismatches in
# registry-core, iam_core's per-application permission lookup). See the script.
COPY docker/patches/patch_platform.py /tmp/patch_platform.py
RUN python3 /tmp/patch_platform.py && rm /tmp/patch_platform.py

# -------------------------------------------------------------- partner API
FROM openg2p/openg2p-registry-partner-api:${RP_VERSION} AS partner-api

ENV REGISTRY_EXTENSION_MODULE=openg2p_registry_da_extension

COPY da-extension/ /app/da-extension/
RUN pip install --no-cache-dir /app/da-extension

COPY docker/patches/patch_platform.py /tmp/patch_platform.py
RUN python3 /tmp/patch_platform.py && rm /tmp/patch_platform.py

# ------------------------------------------------------------------- celery
FROM openg2p/openg2p-registry-celery:${RP_VERSION} AS celery

ENV REGISTRY_EXTENSION_MODULE=openg2p_registry_da_extension

COPY da-extension/ /app/da-extension/
RUN pip install --no-cache-dir /app/da-extension

COPY docker/patches/patch_platform.py /tmp/patch_platform.py
RUN python3 /tmp/patch_platform.py && rm /tmp/patch_platform.py

# ----------------------------------------------------------------- staff UI
# The stock platform UI, unpatched. The bundle patches carried over from the
# farmer registry targeted the minified 1.2.1 build and no longer apply; they
# are kept outside the repo (da-registry/archive/staff-ui-1.2.1-patches) in case
# one turns out to be needed again on this build.
FROM openg2p/openg2p-registry-staff-ui:${STAFF_UI_VERSION} AS staff-ui

# ------------------------------------------------------------------ DB seed
FROM openg2p/openg2p-registry-db-seed:${RP_VERSION} AS db-seed

# Remove the reference registry seed before installing DA metadata.
RUN rm -rf /seed/meta_data/* /seed/awe_meta_data/* /seed/templates/* /seed/seed-data/*

COPY da-extension/src/openg2p_registry_da_extension/meta_data/     /seed/meta_data/
COPY da-extension/src/openg2p_registry_da_extension/awe_meta_data/ /seed/awe_meta_data/
COPY da-extension/src/openg2p_registry_da_extension/templates/     /seed/templates/
COPY docker/db-seed/seed-data/                                     /seed/seed-data/

# Synthetic DAs for local development (LOAD_SAMPLE_DATA=true).
COPY docker/db-seed/load_sample_data.py /seed/load_sample_data.py

RUN chmod +x /seed/load_sample_data.py
