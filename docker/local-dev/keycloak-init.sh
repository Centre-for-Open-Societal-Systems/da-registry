#!/usr/bin/env bash
# Idempotently create the "staff" Keycloak realm, OIDC clients, roles, and
# demo users needed to run the DA Registry locally. Safe to re-run.
#
# Trimmed from openg2p-developer's multi-product keycloak-init.sh down to
# just what da-registry needs: the IAM SSO client, the DA staff
# portal client + its roles, the AWE admin client + resolver, and three
# demo users (staff, plus the two AWE approvers seeded in awe_meta_data).
set -euo pipefail

KEYCLOAK_URL="${KEYCLOAK_URL:-http://keycloak:8080}"
KEYCLOAK_ADMIN="${KEYCLOAK_ADMIN:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-staff}"
IAM_STAFF_PORT="${IAM_STAFF_PORT:-8120}"
DA_REGISTRY_UI_PORT="${DA_REGISTRY_UI_PORT:-3101}"
AWE_UI_PORT="${AWE_UI_PORT:-8131}"
KEYCLOAK_IAM_CLIENT_SECRET="${KEYCLOAK_IAM_CLIENT_SECRET:-dev-iam-staff-secret}"
KEYCLOAK_AWE_RESOLVER_CLIENT_SECRET="${KEYCLOAK_AWE_RESOLVER_CLIENT_SECRET:-dev-awe-resolver-secret}"
KEYCLOAK_DA_BACKEND_CLIENT_SECRET="${KEYCLOAK_DA_BACKEND_CLIENT_SECRET:-dev-da-backend-secret}"
KEYCLOAK_DEV_USER="${KEYCLOAK_DEV_USER:-staff}"
KEYCLOAK_DEV_PASSWORD="${KEYCLOAK_DEV_PASSWORD:-staff}"
# AWE demo approvers (Stage 1 / Stage 2) — matches awe_meta_data/30_approver_rule.sql.
KEYCLOAK_AWE_APPROVER_PASSWORD="${KEYCLOAK_AWE_APPROVER_PASSWORD:-pass}"
AWE_APPROVER_ROLES=(
  "Operations Administrator"
  "Technical Administrator"
)

# Registry staff portal client roles — keep in sync with the roles referenced
# by g2p_register_sections.sql / the staff portal's permission checks.
REGISTRY_STAFF_CLIENT_ROLES=(
  "Intake Officer"
  "Intake Validator"
  "Data Editor"
  "Data Validator"
  "Data Supervisor"
  "Integration Manager"
  "Operations Administrator"
  "Schema Designer"
  "Integration Specialist"
  "Reference Data Specialist"
  "Technical Administrator"
)

KCADM="${KCADM:-/opt/keycloak/bin/kcadm.sh}"

wait_for_keycloak() {
  local host="${KEYCLOAK_HOST:-keycloak}"
  local port="${KEYCLOAK_PORT:-8080}"
  local attempt

  for attempt in $(seq 1 60); do
    if (echo >"/dev/tcp/${host}/${port}") >/dev/null 2>&1; then
      return 0
    fi
    sleep 2
  done
  echo "Keycloak did not become ready at ${KEYCLOAK_URL}" >&2
  return 1
}

kc_login() {
  "${KCADM}" config credentials \
    --server "${KEYCLOAK_URL}" \
    --realm master \
    --user "${KEYCLOAK_ADMIN}" \
    --password "${KEYCLOAK_ADMIN_PASSWORD}" >/dev/null
}

realm_exists() {
  "${KCADM}" get "realms/${KEYCLOAK_REALM}" >/dev/null 2>&1
}

ensure_realm() {
  if realm_exists; then
    echo "[keycloak-init] Realm '${KEYCLOAK_REALM}' already exists"
    return 0
  fi

  echo "[keycloak-init] Creating realm '${KEYCLOAK_REALM}' ..."
  "${KCADM}" create realms \
    -s "realm=${KEYCLOAK_REALM}" \
    -s enabled=true \
    -s sslRequired=none \
    -s registrationAllowed=false \
    -s loginWithEmailAllowed=true \
    -s duplicateEmailsAllowed=false \
    -s resetPasswordAllowed=true \
    -s editUsernameAllowed=false \
    -s bruteForceProtected=false
}

client_internal_id() {
  local client_id="$1"
  "${KCADM}" get clients -r "${KEYCLOAK_REALM}" -q "clientId=${client_id}" --fields id 2>/dev/null \
    | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
    | head -1
}

ensure_client() {
  local client_id="$1"
  shift
  local internal_id
  internal_id="$(client_internal_id "${client_id}" || true)"

  if [[ -z "${internal_id}" ]]; then
    echo "[keycloak-init]   + client ${client_id}"
    "${KCADM}" create clients -r "${KEYCLOAK_REALM}" -s "clientId=${client_id}" "$@"
  else
    echo "[keycloak-init]   ~ client ${client_id}"
    "${KCADM}" update "clients/${internal_id}" -r "${KEYCLOAK_REALM}" "$@"
  fi
}

ensure_client_role() {
  local client_id="$1"
  local role_name="$2"
  local client_uuid
  client_uuid="$(client_internal_id "${client_id}")"
  [[ -n "${client_uuid}" ]] || return 0

  if "${KCADM}" get "clients/${client_uuid}/roles/${role_name}" -r "${KEYCLOAK_REALM}" >/dev/null 2>&1; then
    return 0
  fi

  echo "[keycloak-init]   + client role ${client_id}/${role_name}"
  "${KCADM}" create "clients/${client_uuid}/roles" -r "${KEYCLOAK_REALM}" -s "name=${role_name}" >/dev/null 2>&1 || true
}

assign_client_role() {
  local username="$1"
  local client_id="$2"
  local role_name="$3"

  if ! "${KCADM}" get users -r "${KEYCLOAK_REALM}" -q "username=${username}" -q "exact=true" --fields id >/dev/null 2>&1; then
    return 0
  fi

  "${KCADM}" add-roles \
    -r "${KEYCLOAK_REALM}" \
    --uusername "${username}" \
    --cclientid "${client_id}" \
    --rolename "${role_name}" >/dev/null 2>&1 || true
}

group_internal_id() {
  local group_name="$1"
  "${KCADM}" get groups -r "${KEYCLOAK_REALM}" -q "search=${group_name}" -q "exact=true" --fields id,name 2>/dev/null \
    | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
    | head -1
}

ensure_group_with_client_roles() {
  # ensure_group_with_client_roles <group name> <client id> [<role> ...]
  # Creates the group when missing and grants it the client roles; members
  # get the roles through the group. Idempotent.
  local group_name="$1"
  local client_id="$2"
  shift 2

  if [[ -z "$(group_internal_id "${group_name}")" ]]; then
    echo "[keycloak-init]   + group ${group_name}"
    "${KCADM}" create groups -r "${KEYCLOAK_REALM}" -s "name=${group_name}" >/dev/null
  else
    echo "[keycloak-init]   ~ group ${group_name}"
  fi

  (( $# )) || return 0
  local args=()
  for role in "$@"; do
    args+=(--rolename "${role}")
  done
  "${KCADM}" add-roles -r "${KEYCLOAK_REALM}" --gname "${group_name}" \
    --cclientid "${client_id}" "${args[@]}" >/dev/null 2>&1 || true
}

assign_realm_management_role() {
  local service_account_username="$1"
  local role_name="$2"

  "${KCADM}" add-roles \
    -r "${KEYCLOAK_REALM}" \
    --uusername "${service_account_username}" \
    --cclientid realm-management \
    --rolename "${role_name}" >/dev/null 2>&1 || true
}

ensure_user() {
  # ensure_user <username> <password> <email> <firstName> <lastName>
  local username="$1"
  local password="$2"
  local email="$3"
  local first_name="$4"
  local last_name="$5"
  local user_id

  # Keycloak's username query is a substring match by default (exact=true
  # is required for an exact match) — without it, looking up "admin" can
  # match unrelated users like "service-account-awe-admin-resolver" and
  # cause this function to silently skip creating the real user.
  user_id="$("${KCADM}" get users -r "${KEYCLOAK_REALM}" -q "username=${username}" -q "exact=true" --fields id 2>/dev/null \
    | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
    | head -1)"

  if [[ -z "${user_id}" ]]; then
    echo "[keycloak-init] Creating user '${username}'"
    "${KCADM}" create users -r "${KEYCLOAK_REALM}" \
      -s "username=${username}" \
      -s enabled=true \
      -s "email=${email}" \
      -s emailVerified=true \
      -s "firstName=${first_name}" \
      -s "lastName=${last_name}"
  else
    echo "[keycloak-init] User '${username}' already exists"
  fi

  "${KCADM}" set-password -r "${KEYCLOAK_REALM}" \
    --username "${username}" \
    --new-password "${password}" \
    --temporary=false
}

ensure_dev_user() {
  ensure_user \
    "${KEYCLOAK_DEV_USER}" \
    "${KEYCLOAK_DEV_PASSWORD}" \
    "${KEYCLOAK_DEV_USER}@localhost" \
    "Local" \
    "Developer"

  for role in "${REGISTRY_STAFF_CLIENT_ROLES[@]}"; do
    assign_client_role "${KEYCLOAK_DEV_USER}" "da-registry-staff-portal" "${role}"
  done

  assign_client_role "${KEYCLOAK_DEV_USER}" "awe-admin-portal" "AWE_ADMIN"
}

# Staff-realm admin login, distinct from the Keycloak master-realm bootstrap
# admin (KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD, master realm only — can't log
# into the staff portal at all). This one is a real staff-portal user with
# every role, seeded as an additional AWE approver (see awe_meta_data).
KEYCLOAK_STAFF_ADMIN_USER="${KEYCLOAK_STAFF_ADMIN_USER:-admin}"
KEYCLOAK_STAFF_ADMIN_PASSWORD="${KEYCLOAK_STAFF_ADMIN_PASSWORD:-admin}"

ensure_staff_admin_user() {
  ensure_user \
    "${KEYCLOAK_STAFF_ADMIN_USER}" \
    "${KEYCLOAK_STAFF_ADMIN_PASSWORD}" \
    "${KEYCLOAK_STAFF_ADMIN_USER}@localhost" \
    "Staff" \
    "Admin"

  for role in "${REGISTRY_STAFF_CLIENT_ROLES[@]}"; do
    assign_client_role "${KEYCLOAK_STAFF_ADMIN_USER}" "da-registry-staff-portal" "${role}"
  done

  assign_client_role "${KEYCLOAK_STAFF_ADMIN_USER}" "awe-admin-portal" "AWE_ADMIN"
}

# AWE seeded policies use alex.carter (Stage 1) and nina.patel (Stage 2).
ensure_awe_approver_users() {
  local username role

  echo "[keycloak-init] Ensuring AWE approver users (Op Admin + Tech Admin) ..."

  ensure_user "alex.carter" "${KEYCLOAK_AWE_APPROVER_PASSWORD}" \
    "alex.carter@email.com" "Alex" "Carter"
  ensure_user "nina.patel" "${KEYCLOAK_AWE_APPROVER_PASSWORD}" \
    "nina.patel@email.com" "Nina" "Patel"

  for username in alex.carter nina.patel; do
    for role in "${AWE_APPROVER_ROLES[@]}"; do
      assign_client_role "${username}" "da-registry-staff-portal" "${role}"
    done
  done
}

# A Development Agent's own record: the user attribute `da_id` (their DA-ID)
# is mapped into the access token as the claim `da_id`. The registry's staff
# API then limits that user to their own DA record (da-extension
# register_domain/services/da_own_record.py). The scope is a default scope of
# every client a DA may sign in with, so the claim is always in the token.
ensure_da_self_service_scope() {
  local scope_id
  # Keycloak 26 drops user attributes it does not know (user profile). Let
  # administrators set `da_id` (and any other unmanaged attribute) on users.
  "${KCADM}" update users/profile -r "${KEYCLOAK_REALM}" -s unmanagedAttributePolicy=ADMIN_EDIT >/dev/null 2>&1 || true
  scope_id="$("${KCADM}" get client-scopes -r "${KEYCLOAK_REALM}" --fields id,name --format csv --noquotes 2>/dev/null \
    | { grep ',da-self-service$' || true; } | cut -d, -f1 | head -1)"
  if [[ -z "${scope_id}" ]]; then
    echo "[keycloak-init] Creating client scope 'da-self-service' (claim da_id)"
    "${KCADM}" create client-scopes -r "${KEYCLOAK_REALM}" \
      -s name=da-self-service -s protocol=openid-connect \
      -s 'attributes."include.in.token.scope"=true' -s 'attributes."display.on.consent.screen"=false' >/dev/null
    scope_id="$("${KCADM}" get client-scopes -r "${KEYCLOAK_REALM}" --fields id,name --format csv --noquotes 2>/dev/null \
    | { grep ',da-self-service$' || true; } | cut -d, -f1 | head -1)"
    "${KCADM}" create "client-scopes/${scope_id}/protocol-mappers/models" -r "${KEYCLOAK_REALM}" \
      -s name=da_id -s protocol=openid-connect -s protocolMapper=oidc-usermodel-attribute-mapper \
      -s 'config."user.attribute"=da_id' -s 'config."claim.name"=da_id' -s 'config."jsonType.label"=String' \
      -s 'config."access.token.claim"=true' -s 'config."id.token.claim"=true' -s 'config."userinfo.token.claim"=true' >/dev/null
  fi
  local client_id client_uuid
  for client_id in "$@"; do
    client_uuid="$(client_internal_id "${client_id}")"
    [[ -n "${client_uuid}" ]] || continue
    "${KCADM}" update "clients/${client_uuid}/default-client-scopes/${scope_id}" -r "${KEYCLOAK_REALM}" >/dev/null 2>&1 || true
  done
}

# ensure_user_attribute <username> <attribute> <value>
ensure_user_attribute() {
  local user_id
  user_id="$("${KCADM}" get users -r "${KEYCLOAK_REALM}" -q "username=$1" -q "exact=true" --fields id 2>/dev/null \
    | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
  [[ -n "${user_id}" ]] || return 0
  "${KCADM}" update "users/${user_id}" -r "${KEYCLOAK_REALM}" -s "attributes.$2=$3" >/dev/null
}

# Optional local test DA: set KEYCLOAK_DA_TEST_DA_ID to a registered DA-ID
# (e.g. DA-4374521939) and the user da.test (password KEYCLOAK_DA_TEST_PASSWORD,
# default "pass") is created with role Data Editor and attribute da_id, so a
# token for it is limited to that one record (da_own_record.py).
KEYCLOAK_DA_TEST_DA_ID="${KEYCLOAK_DA_TEST_DA_ID:-}"
KEYCLOAK_DA_TEST_PASSWORD="${KEYCLOAK_DA_TEST_PASSWORD:-pass}"
ensure_da_test_user() {
  [[ -n "${KEYCLOAK_DA_TEST_DA_ID}" ]] || return 0
  ensure_user "da.test" "${KEYCLOAK_DA_TEST_PASSWORD}" "da.test@localhost" "Test" "DA"
  assign_client_role "da.test" "da-registry-staff-portal" "Data Editor"
  ensure_user_attribute "da.test" "da_id" "${KEYCLOAK_DA_TEST_DA_ID}"
}

# Three demo users for the two-level approval, one role each (password
# KEYCLOAK_DA_DEMO_PASSWORD, default "pass"):
#   da.officer    Intake Officer + Data Editor   enters / imports DAs
#   da.validator  Intake Validator + Data Validator   approves Stage 1
#   da.approver   Operations Administrator   approves Stage 2 (and Stage 1)
KEYCLOAK_DA_DEMO_PASSWORD="${KEYCLOAK_DA_DEMO_PASSWORD:-pass}"
ensure_da_demo_users() {
  ensure_user "da.officer" "${KEYCLOAK_DA_DEMO_PASSWORD}" "da.officer@localhost" "Intake" "Officer"
  assign_client_role "da.officer" "da-registry-staff-portal" "Intake Officer"
  assign_client_role "da.officer" "da-registry-staff-portal" "Data Editor"
  ensure_user "da.validator" "${KEYCLOAK_DA_DEMO_PASSWORD}" "da.validator@localhost" "Woreda" "Validator"
  assign_client_role "da.validator" "da-registry-staff-portal" "Intake Validator"
  assign_client_role "da.validator" "da-registry-staff-portal" "Data Validator"
  ensure_user "da.approver" "${KEYCLOAK_DA_DEMO_PASSWORD}" "da.approver@localhost" "Operations" "Approver"
  assign_client_role "da.approver" "da-registry-staff-portal" "Operations Administrator"
}

ensure_awe_clients() {
  ensure_client "awe-admin-portal" \
    -s enabled=true \
    -s publicClient=true \
    -s standardFlowEnabled=true \
    -s directAccessGrantsEnabled=true \
    -s 'redirectUris=["http://localhost:'"${AWE_UI_PORT}"'/*"]' \
    -s 'webOrigins=["http://localhost:'"${AWE_UI_PORT}"'"]'

  ensure_client_role "awe-admin-portal" "AWE_ADMIN"
  ensure_client_role "awe-admin-portal" "AWE_VIEWER"

  ensure_client "awe-admin-resolver" \
    -s enabled=true \
    -s publicClient=false \
    -s secret="${KEYCLOAK_AWE_RESOLVER_CLIENT_SECRET}" \
    -s serviceAccountsEnabled=true \
    -s standardFlowEnabled=false \
    -s directAccessGrantsEnabled=false

  for role in view-users view-clients query-groups; do
    assign_realm_management_role "service-account-awe-admin-resolver" "${role}"
  done
}

echo "[keycloak-init] Waiting for Keycloak at ${KEYCLOAK_URL} ..."
wait_for_keycloak
kc_login
ensure_realm

echo "[keycloak-init] Ensuring OIDC clients in realm '${KEYCLOAK_REALM}' ..."

# IAM Staff Portal API — confidential client used for the browser SSO code flow.
IAM_POST_LOGOUT_REDIRECT_URIS="http://localhost:${DA_REGISTRY_UI_PORT}/*##http://localhost:${IAM_STAFF_PORT}/auth/callback"
IAM_CLIENT_ATTRIBUTES="$(printf '{"post.logout.redirect.uris":"%s"}' "${IAM_POST_LOGOUT_REDIRECT_URIS}")"
ensure_client "iam-staff-portal" \
  -s enabled=true \
  -s publicClient=false \
  -s secret="${KEYCLOAK_IAM_CLIENT_SECRET}" \
  -s standardFlowEnabled=true \
  -s directAccessGrantsEnabled=true \
  -s serviceAccountsEnabled=false \
  -s 'redirectUris=["http://localhost:'"${IAM_STAFF_PORT}"'/auth/callback","http://localhost:'"${DA_REGISTRY_UI_PORT}"'/*"]' \
  -s 'webOrigins=["+"]' \
  -s "attributes=${IAM_CLIENT_ATTRIBUTES}"

ensure_client "da-registry-staff-portal" \
  -s enabled=true \
  -s publicClient=true \
  -s standardFlowEnabled=true \
  -s directAccessGrantsEnabled=true \
  -s 'redirectUris=["http://localhost:'"${DA_REGISTRY_UI_PORT}"'/*"]' \
  -s 'webOrigins=["http://localhost:'"${DA_REGISTRY_UI_PORT}"'"]'

# The DA registry services (staff API, partner API, celery) read geo levels and
# code lists from the Master Data API with this client's token (client
# credentials), as the livestock registry does on platform 1.2.
ensure_client "da-registry-backend" \
  -s enabled=true \
  -s publicClient=false \
  -s secret="${KEYCLOAK_DA_BACKEND_CLIENT_SECRET}" \
  -s serviceAccountsEnabled=true \
  -s standardFlowEnabled=false \
  -s directAccessGrantsEnabled=false

ensure_awe_clients

ensure_da_self_service_scope "iam-staff-portal" "da-registry-staff-portal"
ensure_da_test_user
ensure_da_demo_users

for role in "${REGISTRY_STAFF_CLIENT_ROLES[@]}"; do
  ensure_client_role "da-registry-staff-portal" "${role}"
done

# DA Services roles -> DA registry roles (DA-165; docs/rbac-registry-roles.md).
# A DA Services user is put in the group of their role; the group carries the
# registry roles. Where a user may act (their Woreda / Zone / Region) is a
# separate DP_ data-policy role (DA-166, scripts/da-scope-local.sh).
echo "[keycloak-init] Ensuring DA Services role groups ..."
ensure_group_with_client_roles "DA Services - Development Agent" "da-registry-staff-portal" \
  "Data Editor"
ensure_group_with_client_roles "DA Services - Supervisor" "da-registry-staff-portal" \
  "Intake Officer" "Intake Validator" "Data Editor" "Data Validator" "Data Supervisor"
ensure_group_with_client_roles "DA Services - Executive" "da-registry-staff-portal" \
  "Data Supervisor"
ensure_group_with_client_roles "DA Services - OAN Administrator" "da-registry-staff-portal" \
  "Operations Administrator" "Intake Officer" "Intake Validator" "Data Editor" "Data Validator" "Data Supervisor"
# No registry roles: Communications Officers do not see DA records.
ensure_group_with_client_roles "DA Services - Communications Officer" "da-registry-staff-portal"

ensure_dev_user
ensure_staff_admin_user
ensure_awe_approver_users

echo "[keycloak-init] Done. Realm: ${KEYCLOAK_URL}/realms/${KEYCLOAK_REALM}"
echo "[keycloak-init] Dev login: ${KEYCLOAK_DEV_USER} / ${KEYCLOAK_DEV_PASSWORD}"
echo "[keycloak-init] Staff admin login: ${KEYCLOAK_STAFF_ADMIN_USER} / ${KEYCLOAK_STAFF_ADMIN_PASSWORD}"
echo "[keycloak-init] AWE Stage 1 approver: alex.carter / ${KEYCLOAK_AWE_APPROVER_PASSWORD}"
echo "[keycloak-init] AWE Stage 2 approver: nina.patel / ${KEYCLOAK_AWE_APPROVER_PASSWORD}"
