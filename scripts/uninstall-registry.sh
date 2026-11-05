#!/usr/bin/env bash
#
# uninstall-registry.sh
# ---------------------
# Cleanly uninstall an OpenG2P Registry (Gen 2) Helm release and every
# resource it touched, including the PostgreSQL databases and roles that
# live inside the commons-postgresql instance (which are NOT owned by the
# registry Helm release and therefore survive `helm uninstall`).
#
# What it does, in order:
#   1. Remove this registry's Superset     (dashboards/charts/datasets + the
#      dashboards                           database connection, which live in
#                                           the SHARED Superset release and so
#                                           survive `helm uninstall`. Runs FIRST,
#                                           while `helm get values` can still be
#                                           read for the connection name. A no-op
#                                           unless this variant ships dashboards.)
#   2. helm uninstall <release>            (registry workloads, services,
#                                           helm-owned secrets & configmaps)
#   3. Delete leftover Jobs + their Pods   (helm hook jobs like db-seed,
#                                           keycloak-init, postgres-init, and the
#                                           sanity jobs (pm-seed, cm-seed, sanity)
#                                           keep themselves around via
#                                           hook-delete-policy: before-hook-creation)
#   4. Sweep leftover Secrets/ConfigMaps   (label: app.kubernetes.io/instance)
#   5. Drop Postgres databases + roles     (via `kubectl exec` into
#                                           commons-postgresql-0)
#   6. Delete this registry's IAM rows     (staff_portal_applications +
#                                           staff_roles / permissions / mappings
#                                           for mnemonic <release>-staff-portal,
#                                           in the IAM DB inside the same
#                                           commons-postgresql instance)
#   7. Delete PVCs by label                (app.kubernetes.io/instance)
#   8. Delete PVs still bound to those PVCs
#      (typically `Released` PVs created with reclaimPolicy=Retain)
#
# NOT removed (by design): the sanity e2e seeds a SHARED, persistent test partner
# into Partner Management (PARTNER_CM_SANITY key) and a binding+policy into the
# Consent Manager (FR_SANITY_PARTNER). Those live in PM's / CM's own databases —
# not in this registry's release or DBs — and are intentionally left in place:
# PARTNER_CM_SANITY is shared with the Consent Manager's own sanity, and CM
# partner-delete is soft (audit integrity). Remove them via PM/CM if desired.
#
# Requires: kubectl (cluster admin), helm, bash 4+.
#
# USAGE:
#   ./uninstall-registry.sh \
#       --namespace <ns> \
#       [--release <name>]            (default: registry)
#       [--postgres-release <name>]   (default: commons-postgresql)
#       [--postgres-namespace <ns>]   (default: same as --namespace)
#       [--iam-db <name>]             (default: iam; IAM staff-portal DB to clean)
#       [--keep-iam]                  (do NOT delete this registry's IAM rows)
#       [--keep-dashboards]           (do NOT remove this registry's Superset assets)
#       [--superset-release <name>]   (default: commons-services)
#       [--superset-namespace <ns>]   (default: same as --namespace)
#       [--superset-db-name <name>]   (default: read from the release's values)
#       [--keep-pvs]                  (delete PVCs but not PVs)
#       [--dry-run]                   (print actions, change nothing)
#       [--yes]                       (skip interactive confirmation)
#
# EXAMPLES:
#   # Dry run first — no changes made:
#   ./uninstall-registry.sh --namespace registry --dry-run
#
#   # For real, with confirmation prompt:
#   ./uninstall-registry.sh --namespace registry
#
#   # Non-interactive (CI / scripted):
#   ./uninstall-registry.sh --namespace registry --yes

set -euo pipefail

# ---------- defaults ----------
RELEASE="registry"
NAMESPACE=""
POSTGRES_RELEASE="commons-postgresql"
POSTGRES_NAMESPACE=""
IAM_DB="iam"
KEEP_IAM=false
KEEP_PVS=false
DRY_RUN=false
ASSUME_YES=false
# Superset is a SHARED release (commons-services), not part of this registry.
# SUPERSET_DB_NAME is auto-read from the release's own values below; the flag is
# only needed when the release is already gone.
SUPERSET_RELEASE="commons-services"
SUPERSET_NAMESPACE=""
SUPERSET_DB_NAME=""
KEEP_DASHBOARDS=false

# ---------- cli ----------
usage() { sed -n '2,70p' "$0"; exit 1; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release)           RELEASE="$2";           shift 2 ;;
    --namespace|-n)      NAMESPACE="$2";         shift 2 ;;
    --postgres-release)  POSTGRES_RELEASE="$2";  shift 2 ;;
    --postgres-namespace) POSTGRES_NAMESPACE="$2"; shift 2 ;;
    --iam-db)            IAM_DB="$2";            shift 2 ;;
    --keep-iam)          KEEP_IAM=true;          shift ;;
    --keep-dashboards)   KEEP_DASHBOARDS=true;   shift ;;
    --superset-release)  SUPERSET_RELEASE="$2";  shift 2 ;;
    --superset-namespace) SUPERSET_NAMESPACE="$2"; shift 2 ;;
    --superset-db-name)  SUPERSET_DB_NAME="$2";  shift 2 ;;
    --keep-pvs)          KEEP_PVS=true;          shift ;;
    --dry-run)           DRY_RUN=true;           shift ;;
    --yes|-y)            ASSUME_YES=true;        shift ;;
    -h|--help)           usage ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

[[ -z "$NAMESPACE" ]] && { echo "ERROR: --namespace is required"; exit 1; }
[[ -z "$POSTGRES_NAMESPACE" ]] && POSTGRES_NAMESPACE="$NAMESPACE"
[[ -z "$SUPERSET_NAMESPACE" ]] && SUPERSET_NAMESPACE="$NAMESPACE"

# ---------- derived: DB / user names (templated exactly like values.yaml) ----------
# values.yaml:
#   registryDB:        '{{ .Release.Name | replace "-" "_" }}'
#   registryDBUser:    '{{ printf "%s_user" .Release.Name | replace "-" "_" }}'
#   idGeneratorDB:     '{{ printf "%s_idgenerator" .Release.Name | replace "-" "_" }}'
#   idGeneratorDBUser: '{{ printf "%s_idgenerator_user" .Release.Name | replace "-" "_" }}'
RELEASE_UNDERSCORED="${RELEASE//-/_}"
REGISTRY_DB="${RELEASE_UNDERSCORED}"
REGISTRY_USER="${RELEASE_UNDERSCORED}_user"
IDGEN_DB="${RELEASE_UNDERSCORED}_idgenerator"
IDGEN_USER="${RELEASE_UNDERSCORED}_idgenerator_user"
# AWE (Approval Workflow Engine) subchart runs under the same release. Its
# DB/role live in commons-postgresql too and survive `helm uninstall` — they
# MUST be dropped here, else the role keeps its old password while a reinstall
# regenerates the `<release>-awe` secret, and the AWE pod hangs on auth.
#   values.yaml: aweDB '{{ .Release.Name }}_awe', aweDBUser '{{ .Release.Name }}_awe_user'
AWE_DB="${RELEASE_UNDERSCORED}_awe"
AWE_USER="${RELEASE_UNDERSCORED}_awe_user"

# IAM staff-portal application mnemonic == the per-release Keycloak client_id,
# templated in values.yaml as `{{ .Release.Name }}-staff-portal` (hyphenated,
# NOT underscored like the DB names above).
IAM_APP_MNEMONIC="${RELEASE}-staff-portal"

# ---------- helpers ----------
_red()   { printf "\033[31m%s\033[0m\n" "$*"; }
_green() { printf "\033[32m%s\033[0m\n" "$*"; }
_yellow(){ printf "\033[33m%s\033[0m\n" "$*"; }
_blue()  { printf "\033[34m%s\033[0m\n" "$*"; }

run() {
  # Print + execute, or just print if --dry-run.
  # Never aborts the script on non-zero exit — cleanup commands must be
  # idempotent. Already-deleted resources produce a notice and we move on.
  echo "  \$ $*"
  if [[ "$DRY_RUN" == false ]]; then
    eval "$@" || _yellow "  (command returned non-zero — continuing)"
  fi
}

# Run a shell snippet, honouring DRY_RUN. Use when `run` can't quote safely.
run_block() {
  local label="$1"; shift
  echo "  [${label}]"
  if [[ "$DRY_RUN" == false ]]; then
    "$@" || _yellow "  (block returned non-zero — continuing)"
  fi
}

kexec_psql() {
  # Run SQL as postgres superuser inside the commons-postgresql pod.
  # Uses PGPASSWORD from the pod's env so no secret reads are needed on
  # the admin's machine. Tolerant of failure — script continues.
  local sql="$1"
  local cmd=(kubectl exec -n "$POSTGRES_NAMESPACE" "$PG_POD" -c postgresql -- \
             bash -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql -U postgres -v ON_ERROR_STOP=0 -c \"$sql\"")
  echo "  \$ psql -U postgres -c \"$sql\""
  if [[ "$DRY_RUN" == false ]]; then
    "${cmd[@]}" || _yellow "  (psql returned non-zero — continuing)"
  fi
}

kexec_psql_db() {
  # Like kexec_psql, but connects to a specific database (-d). Used to clean
  # this registry's rows out of the IAM staff-portal database, which lives in
  # the same commons-postgresql instance. Tolerant of failure — continues.
  local db="$1"
  local sql="$2"
  local cmd=(kubectl exec -n "$POSTGRES_NAMESPACE" "$PG_POD" -c postgresql -- \
             bash -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql -U postgres -d \"$db\" -v ON_ERROR_STOP=0 -c \"$sql\"")
  echo "  \$ psql -U postgres -d $db -c \"$sql\""
  if [[ "$DRY_RUN" == false ]]; then
    "${cmd[@]}" || _yellow "  (psql returned non-zero — continuing)"
  fi
}

kexec_psql_capture() {
  # Run a read-only query and echo the trimmed result to stdout. Quiet (no
  # command echo, errors suppressed) — used for existence checks so we can skip
  # gracefully when the IAM DB / tables are absent. Returns empty on any error.
  local db="$1"
  local sql="$2"
  kubectl exec -n "$POSTGRES_NAMESPACE" "$PG_POD" -c postgresql -- \
    bash -c "PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql -U postgres -d \"$db\" -tAc \"$sql\"" 2>/dev/null \
    | tr -d '[:space:]' || true
}

# ---------- pre-flight ----------
_blue "==> Pre-flight checks"

command -v kubectl >/dev/null || { _red "kubectl not found"; exit 1; }
command -v helm    >/dev/null || { _red "helm not found";    exit 1; }

if kubectl get ns "$NAMESPACE" >/dev/null 2>&1; then
  NAMESPACE_EXISTS=true
  _green "  Namespace '$NAMESPACE' exists"
else
  NAMESPACE_EXISTS=false
  _yellow "  Namespace '$NAMESPACE' does not exist — namespace-scoped cleanup will be skipped"
fi

# Locate commons-postgresql pod. Bitnami's chart gives it these labels.
PG_POD=""
if kubectl get ns "$POSTGRES_NAMESPACE" >/dev/null 2>&1; then
  PG_POD=$(kubectl get pod -n "$POSTGRES_NAMESPACE" \
    -l "app.kubernetes.io/instance=$POSTGRES_RELEASE,app.kubernetes.io/name=postgresql" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)

  # Fallback: by name.
  if [[ -z "$PG_POD" ]]; then
    if kubectl get pod -n "$POSTGRES_NAMESPACE" "${POSTGRES_RELEASE}-0" >/dev/null 2>&1; then
      PG_POD="${POSTGRES_RELEASE}-0"
    fi
  fi
fi

if [[ -z "$PG_POD" ]]; then
  PG_POD_FOUND=false
  _yellow "  commons-postgresql pod not found — DB / role drop step will be skipped"
  _yellow "  (tried label app.kubernetes.io/instance=$POSTGRES_RELEASE and pod name ${POSTGRES_RELEASE}-0 in namespace '$POSTGRES_NAMESPACE')"
else
  PG_POD_FOUND=true
  _green "  Found Postgres pod: $PG_POD (namespace: $POSTGRES_NAMESPACE)"
fi

# Helm release presence is not strictly required (user may have already uninstalled
# and is now running the cleanup half). Note it but don't abort.
if helm -n "$NAMESPACE" status "$RELEASE" >/dev/null 2>&1; then
  _green "  Helm release '$RELEASE' found in namespace '$NAMESPACE'"
  HELM_RELEASE_EXISTS=true
else
  _yellow "  Helm release '$RELEASE' not found — will skip helm uninstall step"
  HELM_RELEASE_EXISTS=false
fi

# Superset connection name: read from the release's own values so the caller does
# not have to know it. Only possible while the release still exists — hence the
# dashboard step runs before `helm uninstall`. --superset-db-name overrides, and
# is the escape hatch when the release is already gone.
if [[ "$KEEP_DASHBOARDS" == false && -z "$SUPERSET_DB_NAME" && "$HELM_RELEASE_EXISTS" == true ]]; then
  SUPERSET_DB_NAME=$(helm -n "$NAMESPACE" get values "$RELEASE" -a -o json 2>/dev/null \
    | jq -r '.analytics.dashboards.supersetDatabaseName // empty' 2>/dev/null || true)
fi

# Fall back to this registry's own connection name when the release is already
# gone — which is the COMMON case, not the exotic one: uninstalling from Rancher,
# or running `helm uninstall` before this script, removes the release and with it
# the only place the name was being read from. The step then skipped quietly and
# left the dashboards, charts, datasets and the database connection behind in the
# shared Superset, where the next install silently adopted them.
#
# This script belongs to ONE registry, so it knows its own name. --superset-db-name
# still overrides, for a deployment that renamed the connection.
if [[ "$KEEP_DASHBOARDS" == false && -z "$SUPERSET_DB_NAME" ]]; then
  SUPERSET_DB_NAME="FR"
  _yellow "  Superset connection: release gone, assuming '$SUPERSET_DB_NAME' (override with --superset-db-name)"
fi

# Locate the shared Superset pod. Its app context is already configured in-pod, so
# the cleanup runs there rather than re-plumbing Superset's config/secrets here.
SUPERSET_POD=""
if [[ "$KEEP_DASHBOARDS" == false && -n "$SUPERSET_DB_NAME" ]] \
   && kubectl get ns "$SUPERSET_NAMESPACE" >/dev/null 2>&1; then
  SUPERSET_POD=$(kubectl get pod -n "$SUPERSET_NAMESPACE" \
    -l "app.kubernetes.io/instance=$SUPERSET_RELEASE,app.kubernetes.io/name=superset" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  # Fallback: by name. Exclude the -worker- pod, which has no web app context.
  if [[ -z "$SUPERSET_POD" ]]; then
    SUPERSET_POD=$(kubectl get pod -n "$SUPERSET_NAMESPACE" --no-headers 2>/dev/null \
      | awk -v p="^${SUPERSET_RELEASE}-superset-" '$1 ~ p && $1 !~ /worker/ && $3 == "Running" {print $1; exit}' || true)
  fi
fi

if [[ "$KEEP_DASHBOARDS" == true ]]; then
  _yellow "  Superset dashboards: skipped (--keep-dashboards)"
elif [[ -z "$SUPERSET_DB_NAME" ]]; then
  _yellow "  Superset dashboards: no connection name found (analytics disabled, or release gone — use --superset-db-name)"
elif [[ -z "$SUPERSET_POD" ]]; then
  _yellow "  Superset dashboards: Superset pod not found in '$SUPERSET_NAMESPACE' — step will be skipped"
else
  _green "  Found Superset pod: $SUPERSET_POD (namespace: $SUPERSET_NAMESPACE, connection: '$SUPERSET_DB_NAME')"
fi

# Remove everything hanging off THIS registry's Superset database connection.
# mode=report prints what would go (used for the preview and --dry-run); mode=delete
# commits. Runs inside the Superset pod so SQLAlchemy handles the relationships —
# safer than deleting metadata rows out from under Superset with psql.
superset_cleanup() {
  local mode="$1" out
  out=$(kubectl exec -n "$SUPERSET_NAMESPACE" -i "$SUPERSET_POD" -c superset -- \
          env SUPERSET_DB_NAME="$SUPERSET_DB_NAME" SUPERSET_CLEAN_MODE="$mode" python - <<'PY' 2>&1 || true
import os, sys
from superset.app import create_app
with create_app().app_context():
    from superset import db
    from superset.models.core import Database
    from superset.models.slice import Slice
    from superset.connectors.sqla.models import SqlaTable

    name = os.environ["SUPERSET_DB_NAME"]
    commit = os.environ.get("SUPERSET_CLEAN_MODE") == "delete"

    database = db.session.query(Database).filter_by(database_name=name).one_or_none()
    if database is None:
        print("[superset] no connection named %r — nothing to remove" % name)
        sys.exit(0)

    datasets = db.session.query(SqlaTable).filter_by(database_id=database.id).all()
    ds_ids = [d.id for d in datasets]
    charts = (db.session.query(Slice)
              .filter(Slice.datasource_id.in_(ds_ids),
                      Slice.datasource_type == "table").all()) if ds_ids else []
    ours = {c.id for c in charts}

    # Only take a dashboard when EVERY chart on it is ours. In a shared Superset a
    # dashboard mixing another tenant's charts must survive, minus our charts.
    candidates, shared = {}, []
    for c in charts:
        for d in c.dashboards:
            candidates[d.id] = d
    mine = []
    for d in candidates.values():
        (mine if all(s.id in ours for s in d.slices) else shared).append(d)

    print("[superset] connection %r: %d dashboard(s), %d chart(s), %d dataset(s)"
          % (name, len(mine), len(charts), len(datasets)))
    for d in shared:
        print("[superset]   KEPT (shared with other charts): dashboard %s %r"
              % (d.id, d.dashboard_title))
    if not commit:
        sys.exit(0)

    for d in mine:
        db.session.delete(d)
    for c in charts:
        db.session.delete(c)
    for t in datasets:
        db.session.delete(t)
    db.session.delete(database)
    db.session.commit()
    print("[superset] removed")
PY
  )
  if printf '%s\n' "$out" | grep -qE '^\[superset\]'; then
    printf '%s\n' "$out" | grep -E '^\[superset\]' | sed 's/^/  /'
  else
    _yellow "  (Superset cleanup produced no result — dashboards left in place)"
    printf '%s\n' "$out" | tail -4 | sed 's/^/    /'
  fi
}

# ---------- show the blast radius ----------
_blue "==> Resources to be deleted"

echo
echo "Helm release:       $RELEASE (namespace: $NAMESPACE)"
echo "Postgres databases: $REGISTRY_DB , $IDGEN_DB , $AWE_DB"
echo "Postgres roles:     $REGISTRY_USER , $IDGEN_USER , $AWE_USER"
echo "Postgres pod:       ${PG_POD:-<not found — will skip DB drop>} ($POSTGRES_NAMESPACE)"
if [[ "$KEEP_IAM" == true ]]; then
  echo "IAM rows:           (skipped — --keep-iam)"
else
  echo "IAM rows:           mnemonic '$IAM_APP_MNEMONIC' in DB '$IAM_DB' (staff_portal_applications + roles/permissions/mappings)"
fi
if [[ "$KEEP_DASHBOARDS" == true ]]; then
  echo "Superset assets:    (skipped — --keep-dashboards)"
elif [[ -n "$SUPERSET_POD" ]]; then
  echo "Superset assets:    connection '$SUPERSET_DB_NAME' in $SUPERSET_RELEASE ($SUPERSET_NAMESPACE):"
  superset_cleanup report
else
  echo "Superset assets:    (none — no Superset pod / connection name resolved)"
fi
echo

if [[ "$NAMESPACE_EXISTS" == true ]]; then
  echo "Jobs (label app.kubernetes.io/instance=$RELEASE):"
  kubectl -n "$NAMESPACE" get job -l "app.kubernetes.io/instance=$RELEASE" \
    --no-headers 2>/dev/null | awk '{print "  - " $1}' || echo "  (none)"

  echo "Secrets (label app.kubernetes.io/instance=$RELEASE):"
  kubectl -n "$NAMESPACE" get secret -l "app.kubernetes.io/instance=$RELEASE" \
    --no-headers 2>/dev/null | awk '{print "  - " $1}' || echo "  (none)"

  echo "ConfigMaps (label app.kubernetes.io/instance=$RELEASE):"
  kubectl -n "$NAMESPACE" get configmap -l "app.kubernetes.io/instance=$RELEASE" \
    --no-headers 2>/dev/null | awk '{print "  - " $1}' || echo "  (none)"

  echo "PVCs (label app.kubernetes.io/instance=$RELEASE):"
  kubectl -n "$NAMESPACE" get pvc -l "app.kubernetes.io/instance=$RELEASE" \
    --no-headers 2>/dev/null | awk '{print "  - " $1}' || echo "  (none)"
else
  echo "(namespace '$NAMESPACE' does not exist — no namespace-scoped resources to preview)"
fi

if [[ "$KEEP_PVS" == false ]]; then
  echo "PVs (bound to above PVCs):"
  if [[ "$NAMESPACE_EXISTS" == true ]]; then
    PVC_NAMES=$(kubectl -n "$NAMESPACE" get pvc -l "app.kubernetes.io/instance=$RELEASE" \
                  -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)
    if [[ -n "$PVC_NAMES" ]]; then
      for pvc in $PVC_NAMES; do
        kubectl get pv -o json 2>/dev/null | \
          jq -r --arg ns "$NAMESPACE" --arg n "$pvc" \
            '.items[] | select(.spec.claimRef.namespace==$ns and .spec.claimRef.name==$n) | "  - " + .metadata.name' \
          2>/dev/null || true
      done
    else
      echo "  (no PVCs; will still check for orphaned PVs claimed by namespace '$NAMESPACE' or labeled with release)"
    fi
  fi
  # Orphaned / Released PVs — show regardless of namespace existence.
  kubectl get pv -o json 2>/dev/null | \
    jq -r --arg ns "$NAMESPACE" --arg rel "$RELEASE" \
      '.items[] | select((.spec.claimRef.namespace==$ns) or (.metadata.labels["app.kubernetes.io/instance"]==$rel)) | "  - " + .metadata.name + " (" + .status.phase + ")"' \
    2>/dev/null | sort -u || true
fi
echo

# ---------- confirmation ----------
if [[ "$DRY_RUN" == true ]]; then
  _yellow "DRY-RUN: no changes will be made."
fi

if [[ "$ASSUME_YES" == false && "$DRY_RUN" == false ]]; then
  _red "This is destructive. Type the release name ('$RELEASE') to confirm:"
  read -r CONFIRM
  if [[ "$CONFIRM" != "$RELEASE" ]]; then
    _red "Confirmation did not match. Aborting."
    exit 1
  fi
fi

# ========== STEP 1: remove this registry's Superset dashboards ==========
# The analytics job imports dashboards into the SHARED Superset — a different Helm
# release — so `helm uninstall` never touches them. Left behind, the dashboards,
# their charts and datasets, and the connection pointing at the registry DB we are
# about to drop all survive, and the next install inherits stale, broken tiles.
#
# Scope is the Superset *database connection* this registry owns (analytics.
# dashboards.supersetDatabaseName). Every asset the bundle imports hangs off it,
# and each tenant in a shared Superset has its own, so nothing else is touched.
# Runs BEFORE `helm uninstall` because the connection name is read from the
# release's values — and there is nothing to gain from doing it later.
_blue "==> [1/8] Remove Superset dashboards"
if [[ "$KEEP_DASHBOARDS" == true ]]; then
  _yellow "  (skipped — --keep-dashboards)"
elif [[ -z "$SUPERSET_DB_NAME" ]]; then
  echo "  (skipped — no Superset connection name; analytics disabled or release already gone)"
elif [[ -z "$SUPERSET_POD" ]]; then
  echo "  (skipped — Superset pod not reachable in namespace '$SUPERSET_NAMESPACE')"
elif [[ "$DRY_RUN" == true ]]; then
  echo "  Would remove, from Superset connection '$SUPERSET_DB_NAME':"
  superset_cleanup report
else
  superset_cleanup delete
fi

# ========== STEP 2: helm uninstall ==========
_blue "==> [2/8] Helm uninstall"
if [[ "$HELM_RELEASE_EXISTS" == true ]]; then
  run "helm uninstall '$RELEASE' -n '$NAMESPACE' --wait --timeout 5m || true"
else
  echo "  (skipped — release not present)"
fi

# ========== STEP 3: delete leftover Jobs (and their Pods) ==========
# Helm hook Jobs (db-seed post-install, keycloak-init, postgres-init) are created
# with `helm.sh/hook-delete-policy: before-hook-creation`, which means they are
# NOT cleaned up by `helm uninstall`. We delete them explicitly here — BEFORE
# dropping the DBs, so their Pods close their Postgres connections cleanly.
_blue "==> [3/8] Delete leftover Jobs and their Pods"
if [[ "$NAMESPACE_EXISTS" == true ]]; then
  run "kubectl -n '$NAMESPACE' delete job -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found --wait=true --timeout=2m"
  # Orphan pods (completed/failed) that a Job left behind after TTL etc.
  run "kubectl -n '$NAMESPACE' delete pod -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found --field-selector=status.phase!=Running"
else
  echo "  (skipped — namespace '$NAMESPACE' not present)"
fi

# ========== STEP 4: sweep leftover Secrets & ConfigMaps ==========
_blue "==> [4/8] Sweep leftover Secrets / ConfigMaps"
if [[ "$NAMESPACE_EXISTS" == true ]]; then
  run "kubectl -n '$NAMESPACE' delete secret    -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found"
  run "kubectl -n '$NAMESPACE' delete configmap -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found"
else
  echo "  (skipped — namespace '$NAMESPACE' not present)"
fi

# ========== STEP 5: drop Postgres DBs & roles ==========
_blue "==> [5/8] Drop Postgres databases and roles"
if [[ "$PG_POD_FOUND" == true ]]; then
  for db in "$REGISTRY_DB" "$IDGEN_DB" "$AWE_DB"; do
    echo "  - Database: $db"
    kexec_psql "REVOKE CONNECT ON DATABASE \\\"$db\\\" FROM PUBLIC;"
    kexec_psql "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$db' AND pid <> pg_backend_pid();"
    kexec_psql "DROP DATABASE IF EXISTS \\\"$db\\\";"
  done

  for role in "$REGISTRY_USER" "$IDGEN_USER" "$AWE_USER"; do
    echo "  - Role: $role"
    # Reassign/drop stray ownership outside the dropped DBs (roles can own cluster-wide objects).
    kexec_psql "REASSIGN OWNED BY \\\"$role\\\" TO postgres;"
    kexec_psql "DROP OWNED BY \\\"$role\\\";"
    kexec_psql "DROP ROLE IF EXISTS \\\"$role\\\";"
  done
else
  echo "  (skipped — commons-postgresql pod not reachable; if Postgres is already gone, DBs are gone too)"
fi

# ========== STEP 6: clean this registry's IAM rows ==========
# IAM no longer seeds registry data — each registry self-registers its tile +
# roles/permissions into IAM at install time (keyed by application_mnemonic =
# <release>-staff-portal). `helm uninstall` does not touch IAM, so remove those
# rows here (child rows first). Targeted strictly by this release's mnemonic, so
# it never affects other registries or the keycloak/minio/superset singletons.
_blue "==> [6/8] Clean IAM staff-portal rows"
if [[ "$KEEP_IAM" == true ]]; then
  _yellow "  (skipped — --keep-iam)"
elif [[ "$PG_POD_FOUND" != true ]]; then
  echo "  (skipped — commons-postgresql pod not reachable; cannot reach IAM DB)"
elif [[ "$DRY_RUN" == true ]]; then
  echo "  Would delete IAM rows for mnemonic '$IAM_APP_MNEMONIC' from DB '$IAM_DB' (if the DB/tables exist)"
else
  # Tolerate an absent IAM install: if the IAM DB or its tables don't exist,
  # there is nothing to clean — report and move on without noisy psql errors.
  IAM_DB_EXISTS=$(kexec_psql_capture "postgres" "SELECT 1 FROM pg_database WHERE datname = '$IAM_DB'")
  if [[ "$IAM_DB_EXISTS" != "1" ]]; then
    _yellow "  (skipped — IAM database '$IAM_DB' not found)"
  else
    IAM_TABLE_EXISTS=$(kexec_psql_capture "$IAM_DB" "SELECT to_regclass('public.staff_portal_applications') IS NOT NULL")
    if [[ "$IAM_TABLE_EXISTS" != "t" ]]; then
      _yellow "  (skipped — table staff_portal_applications not found in IAM DB '$IAM_DB')"
    else
      echo "  - Application mnemonic: $IAM_APP_MNEMONIC (DB: $IAM_DB)"
      kexec_psql_db "$IAM_DB" "DELETE FROM staff_role_permissions WHERE role_id IN (SELECT id FROM staff_roles WHERE application_id IN (SELECT id FROM staff_portal_applications WHERE application_mnemonic = '$IAM_APP_MNEMONIC'));"
      kexec_psql_db "$IAM_DB" "DELETE FROM staff_roles WHERE application_id IN (SELECT id FROM staff_portal_applications WHERE application_mnemonic = '$IAM_APP_MNEMONIC');"
      kexec_psql_db "$IAM_DB" "DELETE FROM staff_application_permissions WHERE application_id IN (SELECT id FROM staff_portal_applications WHERE application_mnemonic = '$IAM_APP_MNEMONIC');"
      kexec_psql_db "$IAM_DB" "DELETE FROM staff_portal_applications WHERE application_mnemonic = '$IAM_APP_MNEMONIC';"
    fi
  fi
fi

# ========== STEP 7: PVCs ==========
_blue "==> [7/8] Delete PVCs"
if [[ "$NAMESPACE_EXISTS" == true ]]; then
  run "kubectl -n '$NAMESPACE' delete pvc -l 'app.kubernetes.io/instance=$RELEASE' --ignore-not-found"
else
  echo "  (skipped — namespace '$NAMESPACE' not present; any orphan PVs handled in step 6)"
fi

# ========== STEP 8: PVs ==========
_blue "==> [8/8] Delete PVs"
if [[ "$KEEP_PVS" == true ]]; then
  _yellow "  (skipped — --keep-pvs)"
else
  # Any PV that still references a PVC in $NAMESPACE labeled with our release.
  # After step 4 the PVCs are gone, so rely on claimRef.
  pv_list=$(kubectl get pv -o json 2>/dev/null | \
    jq -r --arg ns "$NAMESPACE" --arg rel "$RELEASE" \
      '.items[] | select(.spec.claimRef.namespace==$ns) | select(.status.phase=="Released" or .status.phase=="Failed") | .metadata.name' \
    2>/dev/null || true)
  # Also pick up PVs that were labeled at creation time.
  pv_labeled=$(kubectl get pv -l "app.kubernetes.io/instance=$RELEASE" \
                 -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)
  pv_all=$(echo "$pv_list $pv_labeled" | tr ' ' '\n' | sort -u | tr '\n' ' ' | sed 's/^ *//;s/ *$//')

  if [[ -z "$pv_all" ]]; then
    echo "  (no PVs to delete)"
  else
    for pv in $pv_all; do
      run "kubectl delete pv '$pv' --ignore-not-found"
    done
  fi
fi

echo
_green "==> Done."
if [[ "$DRY_RUN" == true ]]; then
  _yellow "    (dry-run — nothing was actually changed)"
fi
