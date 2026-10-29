-- Default approvers for the DA stages, the platform's example users:
-- Stage 1 = alex.carter, Stage 2 = nina.patel (seeded into the local
-- Keycloak by docker/local-dev/keycloak-init.sh). They make the workflow
-- testable on a fresh stack; they are not the real approvers.
-- Real approvers are configured per environment in the AWE admin portal,
-- for example a `role` rule (Keycloak client role such as Operations
-- Administrator or Intake Validator on da-registry-staff-portal, AWE's
-- service account needs view-users and view-clients) or named users.
-- Nothing in this repository names an environment's approvers.
-- Stage ids: 3fd0/3fd2 = change request, 3fd1/3fd3 = intake form.
INSERT INTO "public"."approver_rule" (
    "id", "stage_id", "rule_type", "rule_value", "kind", "required", "created_at", "updated_at"
)
SELECT v."id", v."stage_id", v."rule_type", v."rule_value"::json, v."kind",
       v."required"::boolean, v."created_at"::timestamptz, v."updated_at"::timestamptz
FROM (VALUES
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fe0', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd0', 'user', '{"user_id": "alex.carter"}', 'approver', 'FALSE', NOW(), NOW()),
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fe2', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd2', 'user', '{"user_id": "nina.patel"}', 'approver', 'FALSE', NOW(), NOW()),
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fe1', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd1', 'user', '{"user_id": "alex.carter"}', 'approver', 'FALSE', NOW(), NOW()),
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fe3', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd3', 'user', '{"user_id": "nina.patel"}', 'approver', 'FALSE', NOW(), NOW())
) AS v("id","stage_id","rule_type","rule_value","kind","required","created_at","updated_at")
WHERE EXISTS (SELECT 1 FROM "public"."approval_stage" s WHERE s.id = v."stage_id")
ON CONFLICT ("id") DO UPDATE SET
    "stage_id"   = EXCLUDED."stage_id",
    "rule_type"  = EXCLUDED."rule_type",
    "rule_value" = EXCLUDED."rule_value",
    "kind"       = EXCLUDED."kind",
    "required"   = EXCLUDED."required",
    "updated_at" = NOW();
