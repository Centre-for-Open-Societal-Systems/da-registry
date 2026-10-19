-- Register lookup summaries translate returned field names through the domain
-- dictionary. Preserve the API/model key while presenting a readable label.
UPDATE "public"."registry_languages"
SET "domain_translation" = jsonb_set(
    COALESCE("domain_translation"::jsonb, '{}'::jsonb),
    '{record_name}',
    '"Record Name"'::jsonb,
    TRUE
)
WHERE "language_code" = 'en';
