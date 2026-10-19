-- One stage per DA policy; any one assigned approver completes it.
INSERT INTO "public"."approval_stage" (
    "id", "policy_id", "stage_order", "name", "mode", "mode_value", "sla_hours",
    "parallel_group", "skip_if", "on_empty", "on_breach", "escalation_rules_json",
    "created_at", "updated_at"
)
SELECT v."id", v."policy_id", v."stage_order"::int, v."name", v."mode",
       v."mode_value"::int, v."sla_hours"::int, v."parallel_group"::int,
       v."skip_if"::json, v."on_empty", v."on_breach",
       v."escalation_rules_json"::json, v."created_at"::timestamptz, v."updated_at"::timestamptz
FROM (VALUES
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd0', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fc0', 1, 'DA Officer', 'any-n', 1, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd1', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fc1', 1, 'DA Officer', 'any-n', 1, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW())
) AS v("id","policy_id","stage_order","name","mode","mode_value","sla_hours",
        "parallel_group","skip_if","on_empty","on_breach","escalation_rules_json",
        "created_at","updated_at")
WHERE EXISTS (SELECT 1 FROM "public"."approval_policy" p WHERE p.id = v."policy_id")
ON CONFLICT ("id") DO UPDATE SET
    "name"       = EXCLUDED."name",
    "mode"       = EXCLUDED."mode",
    "mode_value" = EXCLUDED."mode_value",
    "updated_at" = NOW();
