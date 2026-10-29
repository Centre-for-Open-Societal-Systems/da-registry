-- Approval stages for the two DA policies: two stages (First approval, then
-- Second approval), each completed by any one of its listed approvers
-- (mode 'any-n', one decision), the same shape in every OAN registry. The
-- approvers are in 30_approver_rule.sql. The upsert sets the mode on stages
-- seeded earlier with mode 'all'. This is the starting configuration only:
-- approvers for a real environment (Woreda supervisors, Keycloak role rules)
-- are configured in the AWE admin portal after deployment (decision of
-- 27-28 Oct 2026, Faiz / Asmit: AWE is configuration).
-- Stage ids: 3fd0/3fd2 = change request, 3fd1/3fd3 = intake form.
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
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd0', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fc0', 1, 'First approval', 'any-n', 1, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd2', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fc0', 2, 'Second approval', 'any-n', 1, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd1', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fc1', 1, 'First approval', 'any-n', 1, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW()),
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fd3', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fc1', 2, 'Second approval', 'any-n', 1, NULL, NULL, 'null', 'block', NULL, 'null', NOW(), NOW())
) AS v("id","policy_id","stage_order","name","mode","mode_value","sla_hours",
        "parallel_group","skip_if","on_empty","on_breach","escalation_rules_json",
        "created_at","updated_at")
WHERE EXISTS (SELECT 1 FROM "public"."approval_policy" p WHERE p.id = v."policy_id")
ON CONFLICT ("id") DO UPDATE SET
    "name"       = EXCLUDED."name",
    "mode"       = EXCLUDED."mode",
    "mode_value" = EXCLUDED."mode_value",
    "updated_at" = NOW();
