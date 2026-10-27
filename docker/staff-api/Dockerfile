# DA Registry — Staff Portal API image.
#
# The registry-platform image supplies the native platform runtime. This image
# only selects and installs the DA domain extension.
ARG RP_VERSION=1.2.2-rc.557
FROM openg2p/openg2p-registry-staff-api:${RP_VERSION}

ENV REGISTRY_EXTENSION_MODULE=openg2p_registry_da_extension

COPY da-extension/ /app/da-extension/
RUN pip install --no-cache-dir /app/da-extension

# Keep the DA registry's existing compatibility fixes until their upstream
# equivalents are present in the selected platform image.
COPY docker/patches/patch_platform.py /tmp/patch_platform.py
RUN python3 /tmp/patch_platform.py && rm /tmp/patch_platform.py
