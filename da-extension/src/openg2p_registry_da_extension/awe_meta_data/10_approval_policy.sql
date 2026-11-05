-- DA approval policies (AWE). Same shape as the farmer seed: insert new rows
-- (untargeted ON CONFLICT DO NOTHING, since approval_policy also has a unique
-- policy_key+version), then refresh the fields this seed owns.
WITH v("id","policy_key","version","name","description","status","artifact_type",
       "created_by","forbid_self_approval","forbid_repeat_approvers") AS (VALUES
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fc0', 'registry.change_request.da', 1, 'Approval of development agent changes', NULL::text, 'active', 'registry.change_request', 'seed', FALSE, FALSE),
    ('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fc1', 'registry.intake_form.da', 1, 'Approval of development agent registration', NULL::text, 'active', 'registry.intake_form', 'seed', FALSE, FALSE)
),
inserted AS (
    INSERT INTO "public"."approval_policy" (
        "id", "policy_key", "version", "name", "description", "status", "artifact_type",
        "created_by", "forbid_self_approval", "forbid_repeat_approvers", "created_at", "updated_at"
    )
    SELECT v."id", v."policy_key", v."version", v."name", v."description", v."status",
           v."artifact_type", v."created_by", v."forbid_self_approval",
           v."forbid_repeat_approvers", NOW(), NOW()
    FROM v
    ON CONFLICT DO NOTHING
)
UPDATE "public"."approval_policy" p
SET "name"                    = v."name",
    "description"             = v."description",
    "artifact_type"           = v."artifact_type",
    "forbid_self_approval"    = v."forbid_self_approval",
    "forbid_repeat_approvers" = v."forbid_repeat_approvers",
    "updated_at"              = NOW()
FROM v
WHERE p."id" = v."id"
  AND (p."name", p."description", p."artifact_type", p."forbid_self_approval", p."forbid_repeat_approvers")
      IS DISTINCT FROM
      (v."name", v."description", v."artifact_type", v."forbid_self_approval", v."forbid_repeat_approvers");
