-- Approvers for the DA stages (stage 3fd0 = change request, 3fd1 = intake form).
--
-- Role rules, not a named user: AWE asks Keycloak for the users that hold the
-- role on the registry's client (`<release>-staff-portal`, i.e.
-- da-registry-staff-portal, which is why the release must be `da-registry`).
-- A stage's rules are unioned, so anyone holding either role is an approver:
--   * Operations Administrator — the registry administrators (every environment)
--   * Intake Validator / Data Validator — the DA Services Supervisor roles
-- Keycloak lists only users that hold the role DIRECTLY; a role that comes
-- through a group (the DA Services role groups) is not seen. Give approvers
-- the role directly, or add a `group` rule once the group exists in that
-- environment (a group rule fails the whole resolution when the group is
-- missing). AWE's resolver client needs view-users and view-clients.
-- Routing a submission to its Woreda's supervisor is DA-33.
INSERT INTO "public"."approver_rule" (
    "id", "stage_id", "rule_type", "rule_value", "kind", "required", "created_at", "updated_at"
)
SELECT v."id", v."stage_id", v."rule_type", v."rule_value"::json, v."kind",
       v."required"::boolean, v."created_at"::timestamptz, v."updated_at"::timestamptz
FROM (VALUES
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fe0', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd0', 'role', '{"role": "Operations Administrator", "client": "da-registry-staff-portal"}', 'approver', 'FALSE', NOW(), NOW()),
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fe2', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd0', 'role', '{"role": "Data Validator", "client": "da-registry-staff-portal"}', 'approver', 'FALSE', NOW(), NOW()),
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fe1', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd1', 'role', '{"role": "Operations Administrator", "client": "da-registry-staff-portal"}', 'approver', 'FALSE', NOW(), NOW()),
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fe3', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd1', 'role', '{"role": "Intake Validator", "client": "da-registry-staff-portal"}', 'approver', 'FALSE', NOW(), NOW())
) AS v("id","stage_id","rule_type","rule_value","kind","required","created_at","updated_at")
WHERE EXISTS (SELECT 1 FROM "public"."approval_stage" s WHERE s.id = v."stage_id")
ON CONFLICT ("id") DO UPDATE SET
    "rule_type"  = EXCLUDED."rule_type",
    "rule_value" = EXCLUDED."rule_value",
    "kind"       = EXCLUDED."kind",
    "required"   = EXCLUDED."required",
    "updated_at" = NOW();
