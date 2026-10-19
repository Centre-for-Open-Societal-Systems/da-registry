# OpenG2P DA Registry

A ready-to-install **DA Registry** built on the OpenG2P registry platform.

This package is a thin overlay over the shared **openg2p-registry** chart: it
adds the DA domain (registers, schemas, seed metadata and DCI templates) via
the DA-built images, and reuses the platform's service templates, IAM/Keycloak
wiring, db-seed machinery and sanity suite unchanged.

- **Platform chart & images:** published by
  [registry-platform](https://github.com/OpenG2P/registry-platform); this chart
  pins a specific `openg2p-registry` version as a dependency.
- **What to set:** the ingress host (`global.registryHostname`) and, for a real
  environment, the shared commons endpoints (Postgres, Keycloak, Consent/Partner
  Management, AWE, Audit) via the inherited `global.*` values.
- **Sanity suite:** set `registry.sanity.runE2e=true` to run the full end-to-end
  check (DCI search + change-request → AWE approval) after install.

See the deployment docs at [docs.openg2p.org](https://docs.openg2p.org).
