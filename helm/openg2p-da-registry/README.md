# OAN DA Registry

OpenAgriNet (OAN) application developed in the Centre for Open Societal Systems
(COSS) repositories. This chart reuses the pinned OpenG2P registry platform.

| Source | GitHub repository |
| --- | --- |
| OAN application | [da-registry](https://github.com/Centre-for-Open-Societal-Systems/da-registry) |
| OAN Helm sources | [oan-helm](https://github.com/Centre-for-Open-Societal-Systems/oan-helm/tree/main/charts/openg2p-da-registry) |

The Helm chart name retains its `openg2p-` prefix to preserve the existing release
and resource names. It does not identify the application source owner. The
OpenG2P dependency repository contains reused platform templates; application
images and provenance are configured by this OAN chart.

Use chart version **1.0.0-dev.5** and upgrade the current release in its current
namespace. Review private values, image digests and namespace-local Secret
references before applying changes. Optional dashboard components remain at
their explicit enablement settings; DA workloads await verified images/config.

See [included services](https://github.com/Centre-for-Open-Societal-Systems/oan-helm/blob/main/docs/service-catalog.md),
[readiness](https://github.com/Centre-for-Open-Societal-Systems/oan-helm/blob/main/docs/readiness.md) and
[Rancher instructions](https://github.com/Centre-for-Open-Societal-Systems/oan-helm/blob/main/docs/rancher-dev.md).

Dev URLs use `<service>.development.oanstaging.com`. The environment-owned
wildcard DNS/TLS and `istio-system/development` Gateway must be prepared first.
See the service onboarding and enablement guide in `docs/service-onboarding.md`.
