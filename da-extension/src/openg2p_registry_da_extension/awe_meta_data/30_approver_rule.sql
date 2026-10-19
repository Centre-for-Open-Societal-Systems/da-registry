-- Approvers for the DA stages. Local dev: the staff-portal `admin` user.
-- TODO(devops): replace with the real DA registry approvers per environment.
INSERT INTO "public"."approver_rule" (
    "id", "stage_id", "rule_type", "rule_value", "kind", "required", "created_at", "updated_at"
)
SELECT v."id", v."stage_id", v."rule_type", v."rule_value"::json, v."kind",
       v."required"::boolean, v."created_at"::timestamptz, v."updated_at"::timestamptz
FROM (VALUES
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fe0', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd0', 'user', '{"user_id": "admin"}', 'approver', 'FALSE', NOW(), NOW()),
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fe1', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd1', 'user', '{"user_id": "admin"}', 'approver', 'FALSE', NOW(), NOW())
) AS v("id","stage_id","rule_type","rule_value","kind","required","created_at","updated_at")
WHERE EXISTS (SELECT 1 FROM "public"."approval_stage" s WHERE s.id = v."stage_id")
ON CONFLICT ("id") DO UPDATE SET
    "rule_type"  = EXCLUDED."rule_type",
    "rule_value" = EXCLUDED."rule_value",
    "kind"       = EXCLUDED."kind",
    "required"   = EXCLUDED."required",
    "updated_at" = NOW();
