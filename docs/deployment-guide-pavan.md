# DA Registry deployment guide (for Pavan and Simret, DevOps)

Prepared by Yash Sontakke, 19 October 2026. Repository
`Centre-for-Open-Societal-Systems/da-registry` (renamed from `DA-registry-backend`),
branch `develop`; OpenG2P registry-platform `1.2.2-rc.544`. The same content as
`DA_Registry_Deployment_Guide.pdf`.

The DA Registry deploys the same way as the farmer, crop and livestock
registries: Jenkins builds and deploys `develop` automatically into its own
namespace on the shared dev cluster, using the shared commons services. This
guide lists the images CI builds, what DevOps must set up once, how a deploy
runs, the setup after the first deploy and the checks to run. The one-time
setup with commands is in `ci/k8s/README.md`.

## 1. Status today

- The code is complete for phase 1 and merged to `develop` (PR #1, #2, #3).
- **Decision (19 Oct 2026):** the DA Registry deploys like farmer, crop and
  livestock. Same dev cluster (RKE2, `10.0.1.58`), its own namespace `da`,
  release `da-registry`, shared commons services, and **Jenkins deploys
  `develop` automatically**. No separate server, no manual Helm by DevOps.
- **The pipeline is in the repository (PR #4):** the `Jenkinsfile` builds and
  pushes the five images, then a Deploy stage on the `vpn-agent2` node runs
  `ci/deploy-da-dev.sh`, which helm-installs the release. The Helm chart
  `helm/openg2p-da-registry` is a thin overlay on the platform chart
  `openg2p-registry` (pinned to `1.2.2-rc.544`). The dev cluster's hosts and
  commons endpoints are in git, in `helm/openg2p-da-registry/values-dev.yaml`;
  secrets are only referenced by name.
- `docker-compose.yml` is a local development stack only. Do not use it, or
  copy its secrets or switches, on a server (section 10).

```text
Git push to develop
  -> Jenkins (any agent): build and push 5 images to ECR (tag = first 12 chars of the commit),
     mint an ECR pull token, stash ci/ + helm/ + token
  -> Jenkins (vpn-agent2): ci/deploy-da-dev.sh <tag>
       preflight (right cluster, namespace, permissions) -> refresh pull secret
       -> helm dependency build -> render + placeholder guard -> helm upgrade --install
       -> wait for the hook Jobs and the rollouts, print logs on failure
  -> Kubernetes pulls the images and rolls out the pods
```

## 2. Decide before the first deployment

**Geography: the DA Registry uses the shared Master Data (no separate one).**
The DA Registry needs the full Ethiopia hierarchy down to Kebele. The shared dev
cluster's Master Data already holds it: the COSS Ethiopia catalogue (14 regions,
125 zones, 1,379 woredas, 19,535 kebeles; ids `region-ET…` to `kebele-ET…`),
loaded on 15 Oct 2026 for the farmer, livestock and crop registries. The DA
Registry uses the same catalogue and ids, so nothing needs to change for DA.
Just confirm on the target environment: Master Data has the Kebele level; on a
new environment load the same catalogue (`ethiopia_geo_seed.sql.gz`, the file
the livestock db-seed also loads), not the official `ETH` country pack (it stops
at Woreda and uses different ids); keep `registry.dbSeed.loadGeoData: false`.

| Decision | Why it matters | Owner |
|---|---|---|
| Master Data access | The registry services call the shared Master Data API as the Keycloak client `da-registry-staff-portal` (created by the chart); the Celery worker also reads the Master Data database, so the `master-data` Secret must exist in namespace `da`. Without these, location lists are empty and bulk import fails. | DevOps |
| Release name = `da-registry` | The chart derives names from the release: Keycloak client `da-registry-staff-portal`, database `da_registry`, user `da_registry_user`, DB secret `da-registry`, AWE callback URL. Keep this name. | DevOps |
| Hostnames | Namespace `da` is decided. The three public hosts in section 4.3 follow crop's pattern; confirm or rename them (then change `values-dev.yaml`). | DevOps |
| Audit and Novu on or off | The platform defaults are on: audit calls `commons-services-auditmanager`, notifications use Novu and its `commons-novu` Secret. Both are **off** in `values-dev.yaml` until DevOps confirms the dev commons has them. | DevOps, PM |
| Auto-approve imports | `DA_AUTO_APPROVE_IMPORTS: "true"` in `values.yaml`: file imports and DA Services pushes are approved without AWE and get a DA-ID at once. Web form entries still go through AWE. Confirm this is wanted on the server. | Shikha (PM) |
| Consent for DCI search | Consent enforcement is on by default on a server. A consent policy for DA Services is needed in the Consent Manager, or a decision to turn it off. | DevOps, Faiz |

## 3. Images (5) and what runs on the cluster

### 3.1 Images Jenkins builds: 5

All five come from the one root `Dockerfile`, one target each. Each extends the
matching OpenG2P platform image from Docker Hub at `1.2.2-rc.544`.

| ECR image | Base image | What is added | Runs as |
|---|---|---|---|
| `staff-api` | `openg2p/openg2p-registry-staff-api` | DA extension + platform fixes (`docker/patches/patch_platform.py`) | Staff API (form, approval, search) |
| `partner-api` | `openg2p/openg2p-registry-partner-api` | DA extension + platform fixes | Partner API (DA Services push, status, exceptions, DCI search) |
| `celery` | `openg2p/openg2p-registry-celery` | DA extension + platform fixes | **Two** workloads from one image: Celery worker and Celery beat |
| `staff-ui` | `openg2p/openg2p-registry-staff-ui` | Nothing (stock platform UI, built for one consistent tag) | Staff portal web UI |
| `db-seed` | `openg2p/openg2p-registry-db-seed` | DA register metadata, AWE workflow, DCI templates | Hook job after install and upgrade |

```text
<AWS_ACCOUNT_ID>.dkr.ecr.ap-south-1.amazonaws.com/openg2p/da-registry/<image>:<tag>

<tag> = first 12 characters of the Git commit (immutable, this is what is deployed)
        + a moving tag develop / staging / main on those branches (not for deploying)
```

### 3.2 What runs after a Helm install

| Workload | Kind | Image from |
|---|---|---|
| staff-portal-api, partner-api, staff-portal-ui, celery-worker, celery-beat-producer | Deployments (5) | DA images |
| db-seed | Job (post-install / post-upgrade hook) | DA image |
| id-generator (with its own DB init) | Deployment | platform chart |
| redis (Celery broker, `da-registry-redis-master`) | StatefulSet | platform chart |
| postgres-init (creates DB + user), keycloak-init (creates the Keycloak client), iam-register (adds the "DA Registry" tile and role catalogue to IAM) | Jobs (hooks) | platform chart |

The DA overlay turns off the platform sanity suite (`registry.sanity.enabled: false`)
and the beneficiary portal stays off (the platform default).

## 4. What the cluster must provide

### 4.1 Shared services (from DevOps)

The dev values are set in `helm/openg2p-da-registry/values-dev.yaml` (taken from
farmer's and crop's dev setup on the same cluster):

| Service | Dev value | Used for |
|---|---|---|
| PostgreSQL | `commons-postgresql.commons.svc.cluster.local` | Registry DB (created by postgres-init); Master Data DB read by the Celery worker |
| Keycloak, realm `staff` | `https://keycloak-development.oanstaging.com` (keycloak-init uses `http://commons-keycloak.commons.svc.cluster.local:80`) | Staff login, registry roles, DA Services role groups |
| IAM | `http://commons-services-iam-staff-portal-api.commons.svc.cluster.local`; public `https://staff-iam-development.oanstaging.com` | Role catalogue, data policies (Woreda / Region scope) |
| Master Data API | `http://commons-services-master-data-api.commons.svc.cluster.local` | Region / Zone / Woreda / Kebele, code lists (section 2) |
| AWE | `http://commons-services-awe.commons.svc.cluster.local`; callback `http://da-registry-staff-portal-api.da.svc.cluster.local/awe/webhooks/decision` (HMAC secret created by the chart) | Approval workflow |
| MinIO | `minio-api.commons-dev.oanstaging.com` (https), Secret `commons-minio` | Import files, documents, DCI templates |
| Redis for login sessions | `commons-redis-master.commons.svc.cluster.local` (the Celery Redis comes with the chart) | Staff API sessions |
| Partner Management, Consent Manager | chart defaults (`commons-services-pm-partner-api`, `commons-services-cm-partner-api`) | Signed partner calls, consent on DCI search |
| Audit Manager, Novu | off in `values-dev.yaml` (section 2) | Audit trail, notifications |

The chart's own short names (`commons-postgresql` etc.) do not resolve from
namespace `da`, which is why every value carries `.commons.svc.cluster.local`.
Cookie domain `.oanstaging.com`, `LOGIN_PROVIDER_ID` `1` (as farmer).

### 4.2 Database and secrets

- postgres-init creates the database `da_registry` and user `da_registry_user`,
  with the password in Secret `da-registry` (key `da-registry-db-user`).
- The Celery worker also reads the Master Data database: `master_data`, user
  `master_data_user`, Secret `master-data`, key `master-data-db-user`. Confirm
  these names on the cluster.
- When the staff API starts, the DA extension adds its own columns and indexes
  to the DA table and fills them for existing rows (location codes etc.). The
  registry DB user must own the tables, which it does when postgres-init created
  them.

### 4.3 Hostnames, DNS and TLS

| Host | Serves |
|---|---|
| `da-portal-development.oanstaging.com` | Staff portal UI |
| `staff-da-development.oanstaging.com` | Staff API |
| `partner-da-development.oanstaging.com` | Partner API (used by DA Services) |

Same pattern and gateway as crop's `crop-registry-development` /
`staff-crop-development` / `partner-crop-development`.
`da-registry-development.oanstaging.com` is already taken by the DA Services
mock frontend, hence `da-portal-`. All three need DNS and TLS. Also add
`https://da-portal-development.oanstaging.com` to `IAM_STAFF_CORS_ALLOW_ORIGINS`
on the IAM chart and roll IAM: IAM reads its CORS list only at start.

### 4.4 Namespace, Jenkins and ECR

- **Namespace `da` and the CI service account `da-ci`:**
  `kubectl apply -f ci/k8s/da-ci-dev.yaml` (namespace, service account, `admin`
  role in the namespace plus the Istio kinds), then
  `ci/k8s/make-da-ci-kubeconfig.sh` writes its kubeconfig.
- **Jenkins:** a multibranch job for the repository (branch `develop`);
  credentials `AWS_ACCOUNT_ID` (secret text, shared with crop and livestock),
  `aws-ecr-creds` (ECR push) and **`da-dev-kubeconfig`** (secret file, the
  kubeconfig above); node `vpn-agent2`. `AWS_ACCOUNT_ID` is a credential, never
  written in the repository.
- **ECR:** the pipeline creates the five repositories
  `openg2p/da-registry/{staff-api,staff-ui,partner-api,celery,db-seed}` on first
  push if `aws-ecr-creds` may create repositories; otherwise create them
  beforehand. Image pulls use the Secret `da-registry-ecr` in namespace `da`,
  which the deploy refreshes with a fresh 12-hour token on every run and
  attaches to the `default` ServiceAccount, so no pull-secret CronJob is needed.
- **Secrets copied into namespace `da`** from `commons`: `commons-postgresql`,
  `commons-keycloak`, `commons-minio`, `master-data`, `awe-db-user`
  (`ci/k8s/README.md` §4). The chart creates the rest: `da-registry`,
  `da-registry-staff-portal`, `da-registry-awe-callback-hmac`,
  `da-registry-idgenerator`.

## 5. Build and push the images

Normal path: every push to `develop` runs the Jenkins job, which builds and
pushes all five images (tag = first 12 characters of the commit, plus a moving
`develop` tag) and then deploys them (section 6). Other branches build and push
only. The console shows the tag.

Manual build (only with approved ECR access; never overwrite an existing tag):

```bash
export AWS_ACCOUNT_ID="<account-id>"
export AWS_REGION="ap-south-1"
export ECR="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"
export IMAGE_TAG="$(git rev-parse HEAD | cut -c1-12)"

aws ecr get-login-password --region "$AWS_REGION" |
  docker login --username AWS --password-stdin "$ECR"

for image in staff-api staff-ui partner-api celery db-seed; do
  docker build \
    --build-arg RP_VERSION=1.2.2-rc.544 \
    --build-arg STAFF_UI_VERSION=1.2.2-rc.544 \
    --target "$image" -f Dockerfile \
    -t "$ECR/openg2p/da-registry/$image:$IMAGE_TAG" .
  docker push "$ECR/openg2p/da-registry/$image:$IMAGE_TAG"
done
```

The platform version is set in four places that must stay equal: `ARG
RP_VERSION` / `STAFF_UI_VERSION` in the `Dockerfile`, `RP_VERSION` in the
`Jenkinsfile`, the `openg2p-registry` dependency in
`helm/openg2p-da-registry/Chart.yaml`, and the compose file.
`scripts/bump-rp-version.sh` moves them together.

## 6. How a deploy runs

The Jenkins Deploy stage (branch `develop` only, node `vpn-agent2`) runs
`ci/deploy-da-dev.sh <tag>` with the `AWS_ACCOUNT_ID` and `da-dev-kubeconfig`
credentials. The script, in order:

1. **Preflight:** refuses any API server other than `https://10.0.1.58:6443`,
   checks the connection, that namespace `da` exists and that `da-ci` may create
   every kind the chart uses (`kubectl auth can-i`).
2. **Pull secret:** writes the ECR token the build agent minted into Secret
   `da-registry-ecr` and attaches it to the `default` ServiceAccount.
3. **`helm dependency build`** (fresh; the lock file is never committed).
4. **Values, three layers:** `values.yaml` (the DA Registry in every
   environment) + `values-dev.yaml` (this cluster's hosts, commons endpoints,
   secret names) + a generated file with the five image tags and the hook
   switches. Nothing is read back from the cluster, so what is deployed is
   always what is in git.
5. **Render and guard:** `helm template` first; a render that still carries a
   `*.openg2p.org` placeholder host fails the build before anything is changed.
6. **`helm upgrade --install`** (timeout 20 min). `db-seed` runs on every
   deploy; `iam-register` only on the first install.
7. **Wait and report:** the five Deployments must roll out (7 min each). On
   failure the console shows the hook Job logs (saved while they ran, since hook
   pods are deleted), the API pod logs, the release history and the warning
   events.

### 6.1 Deploy by hand

The same script, from a machine that reaches the cluster (vpn-agent2):

```bash
KUBECONFIG=<da-ci kubeconfig> AWS_ACCOUNT_ID=<id> ./ci/deploy-da-dev.sh <12-char tag>
```

Without the `.ecr-token` file the existing pull secret is kept. Switches:
`RUN_DB_SEED`, `RUN_IAM_REGISTER` (default `auto`), `HELM_TIMEOUT`,
`ROLLOUT_TIMEOUT`; see the script header.

**Never `kubectl set env` (or edit a Deployment by hand).** Every environment
variable comes from the chart: plain values in `values.yaml` / `values-dev.yaml`,
secrets through `secretKeyRef`. A variable set by hand and the chart's
`secretKeyRef` for the same name conflict, and the next deploy fails or silently
keeps the wrong value; the livestock registry lost three deploys to exactly
this. To change a setting, change the values file and merge.

### 6.2 Staging

Not deployed by this pipeline yet. When it is, a `staging` build will move
staging's Deployments to the new images with `kubectl set image` and run that
build's db-seed as a plain Job, with **no helm upgrade** (staging's release,
values and hosts untouched), as the crop pipeline does.

## 7. Setup after install

These are not done by the chart. Locally `docker/local-dev/keycloak-init.sh`
and `scripts/da-scope-local.sh` do them; on a server they are done once by an
administrator.

### 7.1 DA Services role groups (Keycloak, realm `staff`)

Create these groups and give each group the client roles of
`da-registry-staff-portal` listed:

| Group | Client roles on da-registry-staff-portal |
|---|---|
| DA Services - Development Agent | Data Editor |
| DA Services - Supervisor | Intake Officer, Intake Validator, Data Editor, Data Validator, Data Supervisor |
| DA Services - Executive | Data Supervisor |
| DA Services - OAN Administrator | Operations Administrator, Intake Officer, Intake Validator, Data Editor, Data Validator, Data Supervisor |
| DA Services - Communications Officer | none |

### 7.2 Woreda / Region scope (IAM data policies)

An IAM administrator (`dataPolicy:create`) adds a data policy per area, through
the IAM admin UI or API, for the application `da-registry-staff-portal`: target
`REGISTER_RECORD`, type `ALLOW`, filter on `woreda_code`, `zone_code` or
`region_code`. Example filter for one Woreda:

```json
{"type":"GROUP","operator":"AND","children":[
  {"type":"CONDITION","field_id":"woreda_code","operator":"eq","value":"ET040301"}]}
```

IAM creates the matching Keycloak client role `DP_<mnemonic>`; give it to the
Supervisor (Woreda) or Executive (Region). A user with no policy sees all DAs.
Details: `docs/rbac-registry-roles.md`. The codes are the Master Data P-codes
(for example Woreda `ET040301`).

### 7.3 DA Services as a partner

- Register DA Services in Partner Management with its signing key or
  certificate, so its calls to the partner API pass signature checks.
- Add a consent policy for DA Services in the Consent Manager for DCI search
  (unless consent is turned off, section 2).
- Give the DA Services team the partner API host
  (`partner-da-development.oanstaging.com`) and their partner id.

### 7.4 Staff users

Create the real staff users in the `staff` realm and put them in the groups
above. The local test users (`admin/admin`, `staff/staff`, `da.*`) must not
exist on a server.

## 8. Checks before go-live

| | Check | Expected |
|---|---|---|
| ☐ | Open `https://da-portal-development.oanstaging.com` | Keycloak login, then the staff portal |
| ☐ | IAM portal | "DA Registry" tile is shown |
| ☐ | Open a new DA form, Location section | Region, Zone, Woreda and **Kebele** lists load |
| ☐ | Submit one DA, approve it in AWE | Record is approved, DA-ID `DA-` + 10 digits |
| ☐ | Same Fayda ID again | Refused: "Fayda ID … is already registered" |
| ☐ | Bulk import a small file (`import-templates/`) | Rows become DAs; bad rows show a reason |
| ☐ | DA Services: signed DCI search on the partner API | DAs returned with `region_code` … `kebele_code` |
| ☐ | DA Services: push one DA, then `/partner/da/status` | Status shows the DA-ID |
| ☐ | Unsigned call to the partner API | Refused (signature check on) |
| ☐ | Supervisor user with a Woreda policy | Sees only that Woreda's DAs |

**Import speed:** Celery beat takes 4 records per stage every 20 seconds, about
10-12 DAs a minute. For a large first import, raise the Celery
`NO_OF_TASKS_TO_PROCESS` setting and the worker capacity first.

## 9. Upgrade and rollback

- For each release write down: commit, image tag, chart version, values file
  revision.
- Back up the `da_registry` database before every upgrade.
- Upgrade: merge to `develop` (or press Build on the job). db-seed runs again;
  check its log in the console.
- Rollback: `helm history da-registry -n da`, then
  `helm rollback da-registry <revision> -n da`. A Helm rollback does **not** undo
  database changes; restore the backup if needed.
- Full removal, including databases and IAM rows that `helm uninstall` leaves
  behind: `scripts/uninstall-registry.sh` (cluster admin). Destructive; use only
  on purpose.

## 10. Local stack versus server

These local switches are for the laptop only and must not be copied to a server:

| Local (docker-compose.yml) | Server |
|---|---|
| Partner signature and consent checks off | On (platform default) |
| Audit off | Off until the dev commons has the Audit Manager (section 2) |
| Master Data auth and CSRF off | Shared Master Data with its own auth |
| Own Ethiopia geography with Kebeles (geo-seed job) | Shared Master Data, same Ethiopia catalogue (section 2) |
| Keycloak groups and scopes from `keycloak-init.sh`, `da-scope-local.sh` | Created by admins (section 7) |
| 50 synthetic DAs, test users, default passwords, plain HTTP | No sample data, real users, secrets, TLS |

### Reference

- `ci/k8s/README.md`: the one-time DevOps setup, with commands
- `Jenkinsfile`, `ci/deploy-da-dev.sh`: the pipeline and the deploy script
- `helm/openg2p-da-registry/values.yaml`, `values-dev.yaml`: the chart overlay and the dev cluster values
- `README.md`: layout, DA register, platform version notes
- `docs/rbac-registry-roles.md`: roles and Woreda / Region scope
- `docs/da-services-api-contract.md`, `docs/da-services-staff-api.md`: the APIs DA Services calls
- Contact: Yash Sontakke (DA Registry)
