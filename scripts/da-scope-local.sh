#!/usr/bin/env bash
# Local stack only: limit a staff user of the DA registry to one Woreda, Zone or
# Region. See docs/rbac-registry-roles.md.
#
#   scripts/da-scope-local.sh <woreda|zone|region> <code> <username>
#   scripts/da-scope-local.sh woreda ET010101 da.supervisor
#
# The registry filters what a user sees with OpenG2P data policies: a policy is
# a filter on DA records, and a user holds it as the Keycloak client role
# DP_<mnemonic> on da-registry-staff-portal. This script
#   1. adds the policy DP_DA_<LEVEL>_<code> (woreda_code / zone_code /
#      region_code = <code>) to the IAM database when it is missing,
#   2. creates the matching client role in Keycloak when it is missing,
#   3. gives that role to the user.
# In a deployment an IAM administrator adds the same policy through the IAM
# admin API or UI (dataPolicy:create), which also creates the Keycloak role;
# only step 3 is done per user (or per group).
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <woreda|zone|region> <code> <username>" >&2
  exit 2
fi
level="$(echo "$1" | tr '[:upper:]' '[:lower:]')"
code="$(echo "$2" | tr '[:lower:]' '[:upper:]')"
username="$3"
case "${level}" in
  woreda|zone|region) ;;
  *) echo "level must be woreda, zone or region" >&2; exit 2 ;;
esac
if [[ ! "${code}" =~ ^ET[0-9]+$ ]]; then
  echo "code must be a Master Data P-code such as ET04, ET0403 or ET040301" >&2
  exit 2
fi

REGISTER_ID="6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90"
CLIENT="da-registry-staff-portal"
REALM="staff"
POSTGRES="${POSTGRES_CONTAINER:-da-registry-postgres}"
KEYCLOAK="${KEYCLOAK_CONTAINER:-da-registry-keycloak}"
KC_ADMIN="${KEYCLOAK_ADMIN:-admin}"
KC_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-admin}"

mnemonic="DP_DA_${level^^}_${code}"
expression="{\"type\":\"GROUP\",\"operator\":\"AND\",\"children\":[{\"type\":\"CONDITION\",\"field_id\":\"${level}_code\",\"operator\":\"eq\",\"value\":\"${code}\"}]}"

echo "[da-scope] policy ${mnemonic}: ${level}_code = ${code}"
docker exec -i "${POSTGRES}" psql -U postgres -d iam_staff -v ON_ERROR_STOP=1 -q <<SQL
INSERT INTO data_policies (policy_id, policy_mnemonic, policy_description, register_id,
                           policy_target, policy_type, policy_filter_expression, application_id)
SELECT gen_random_uuid()::text, '${mnemonic}', 'DA registry records in ${level} ${code}', '${REGISTER_ID}',
       'REGISTER_RECORD', 'ALLOW', '${expression}'::json,
       (SELECT id FROM staff_portal_applications WHERE application_mnemonic = '${CLIENT}')
WHERE NOT EXISTS (SELECT 1 FROM data_policies
                  WHERE policy_mnemonic = '${mnemonic}' AND register_id = '${REGISTER_ID}'
                    AND policy_target = 'REGISTER_RECORD');
SQL

echo "[da-scope] Keycloak role ${CLIENT}/${mnemonic} -> ${username}"
docker exec -i "${KEYCLOAK}" bash -s <<KC
set -e
K=/opt/keycloak/bin/kcadm.sh
CFG=/tmp/da-scope-kcadm.config
\$K config credentials --server http://localhost:8080 --realm master \
  --user '${KC_ADMIN}' --password '${KC_ADMIN_PASSWORD}' --config \$CFG >/dev/null
CID=\$(\$K get clients -r ${REALM} -q clientId=${CLIENT} --fields id --config \$CFG \
  | sed -n 's/.*"id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
\$K create clients/\$CID/roles -r ${REALM} -s name='${mnemonic}' \
  -s 'description=DA registry records in ${level} ${code}' --config \$CFG >/dev/null 2>&1 || true
\$K add-roles -r ${REALM} --uusername '${username}' --cclientid ${CLIENT} \
  --rolename '${mnemonic}' --config \$CFG
KC
echo "[da-scope] done; ${username} must sign in again (new token) to see the scope"
