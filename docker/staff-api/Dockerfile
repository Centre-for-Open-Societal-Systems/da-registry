# DA Registry — Staff Portal API image.
#
# The registry-platform image supplies the native platform runtime. This image
# only selects and installs the DA domain extension.
ARG RP_VERSION=1.2.2-rc.614
FROM openg2p/openg2p-registry-staff-api:${RP_VERSION}

ENV REGISTRY_EXTENSION_MODULE=openg2p_registry_da_extension

COPY da-extension/ /app/da-extension/
RUN pip install --no-cache-dir /app/da-extension

