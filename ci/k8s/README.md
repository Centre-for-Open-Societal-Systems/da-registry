# DA Registry on the dev cluster: one-time setup (DevOps)

The DA Registry deploys like the farmer, crop and livestock registries: Jenkins
builds the images on every push to `develop`, pushes them to ECR and runs
`ci/deploy-da-dev.sh` on the `vpn-agent2` node, which helm-installs release
`da-registry` into namespace `da` of the dev cluster (RKE2, `https://10.0.1.58:6443`).
The chart and its environment values are in git
(`helm/openg2p-da-registry/values.yaml`, `values-dev.yaml`); secrets are only
ever referenced by name.

Everything below is done once, by DevOps, before the first deploy. Items are in
the order they are needed. Nothing here is done by the pipeline.

## 1. Namespace and CI service account

```bash
kubectl apply -f ci/k8s/da-ci-dev.yaml
KUBECONFIG=<admin kubeconfig> ./ci/k8s/make-da-ci-kubeconfig.sh > da-ci.kubeconfig
```

Check: `kubectl auth can-i create deployments -n da --as system:serviceaccount:da:da-ci` prints `yes`.

## 2. Jenkins

| Item | Value |
|---|---|
| Multibranch job | this repository (`Centre-for-Open-Societal-Systems/da-registry`), branch `develop` built on push / poll |
| Credential `AWS_ACCOUNT_ID` | Secret text, the AWS account of the ECR registry (shared with crop and livestock; exists) |
| Credential `aws-ecr-creds` | AWS credentials allowed to push to ECR and create repositories (exists) |
| Credential `da-dev-kubeconfig` | Secret file: `da-ci.kubeconfig` from step 1 |
| Node `vpn-agent2` | the node that reaches the dev API server (exists) |

## 3. ECR

The pipeline creates the five repositories on first push
(`openg2p/da-registry/staff-api`, `staff-ui`, `partner-api`, `celery`, `db-seed`,
region `ap-south-1`) if `aws-ecr-creds` may call `ecr:CreateRepository`;
otherwise create them beforehand. The deploy writes a fresh pull token into the
Secret `da-registry-ecr` in namespace `da` and attaches it to the `default`
ServiceAccount on every deploy, so no pull-secret CronJob is needed.

## 4. Secrets to copy into namespace `da`

The chart's Jobs and pods read these by name. All exist in the `commons`
namespace of the dev cluster; copy them (`kubectl get secret <name> -n commons -o yaml`,
drop the namespace and resourceVersion, apply in `da`).

| Secret | Key(s) used | Used by |
|---|---|---|
| `commons-postgresql` | `postgres-password` | postgres-init (creates the `da_registry` DB and user) |
| `commons-keycloak` | `admin-password` | keycloak-init (creates the `da-registry-staff-portal` client) |
| `commons-minio` | `root-user`, `root-password` | APIs, worker, db-seed (templates bucket) |
| `master-data` | `master-data-db-user` | celery worker (import enricher reads the Master Data DB). Confirm the name and key: `global.masterDataDBSecret` in values.yaml |
| `awe-db-user` | `awe-db-user-password` | db-seed (registers the AWE callback secret in AWE's DB) |

The chart creates the rest itself: `da-registry` (DB password), `da-registry-staff-portal`
(Keycloak client secret), `da-registry-awe-callback-hmac`, `da-registry-idgenerator`.
`commons-novu` is optional (notifications are off in values-dev.yaml).

## 5. DNS and TLS (3 hosts)

| Host | Serves |
|---|---|
| `da-portal-development.oanstaging.com` | staff portal UI |
| `staff-da-development.oanstaging.com` | staff API |
| `partner-da-development.oanstaging.com` | partner API (DA Services calls it) |

Same gateway and certificate setup as `crop-registry-development.oanstaging.com`
and its `staff-crop-` / `partner-crop-` names. `da-registry-development.oanstaging.com`
is taken by the DA Services mock frontend, hence `da-portal-`. If the names
change, change them in `helm/openg2p-da-registry/values-dev.yaml` too.

## 6. IAM

- Add `https://da-portal-development.oanstaging.com` to `IAM_STAFF_CORS_ALLOW_ORIGINS`
  on the IAM chart and roll IAM (IAM reads the list at start).
- The "DA Registry" tile and its role catalogue are registered by the chart's
  `iam-register` Job on the first deploy. Nothing to do by hand.

## 7. After the first deploy (DA team with an IAM / Keycloak admin)

Not needed for the deploy itself; needed before DA Services users sign in:

- The five DA Services role groups in Keycloak realm `staff` and the Woreda /
  Region data policies: `docs/rbac-registry-roles.md` §1-2.
- DA Services as a partner (Partner Management key, consent policy) before it
  calls the partner API: `docs/deployment-guide-pavan.md` §7.3.

## Checks before asking for the first build

```bash
kubectl get ns da
kubectl -n da get sa da-ci secret da-ci-token
kubectl -n da get secret commons-postgresql commons-keycloak commons-minio master-data awe-db-user
kubectl -n commons get svc commons-postgresql commons-keycloak commons-services-iam-staff-portal-api \
  commons-services-master-data-api commons-services-awe commons-redis-master
```

Then merge to `develop` (or press Build on the job). A failed deploy prints the
hook Job logs, the API pod logs and the release history in the Jenkins console;
`helm -n da history da-registry` shows the release state.
