-- Kebele code as a filter of the DA list, next to the Region, Zone and Woreda
-- codes, so the four location levels read alike in the staff API (DA Services
-- asked for kebele_code next to woreda_code, 18 Nov 2026).
--
-- The Kebele has no P-code in Master Data: kebele_code is its Master Data id
-- without the "kebele-" prefix, the same value as geo_lowest_level_value_id
-- (geo_codes.py fills it on every save; the startup backfill fills older
-- records).
--
-- The entry is placed right after the Woreda code and the filters are
-- numbered again in their order. Idempotent: nothing happens once it is there.
WITH current AS (
  SELECT filter_schema::jsonb AS fs
  FROM "public"."g2p_register_schemas"
  WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90'
    AND NOT jsonb_path_exists(filter_schema::jsonb, '$[*] ? (@.field_name == "kebele_code")')
),
entries AS (
  SELECT e, (e->>'order')::numeric AS pos
  FROM current, jsonb_array_elements(current.fs) e
  UNION ALL
  SELECT jsonb_build_object(
           'field_name', 'kebele_code', 'display_label', 'Kebele code (Master Data)',
           'filter_type', 'text', 'allowed_operators', jsonb_build_array('eq', 'in')),
         coalesce((SELECT (e->>'order')::numeric FROM current, jsonb_array_elements(current.fs) e
                   WHERE e->>'field_name' = 'woreda_code'), 1000) + 0.5
  FROM current
),
numbered AS (
  SELECT jsonb_set(e, '{order}', to_jsonb(row_number() OVER (ORDER BY pos))) AS e,
         row_number() OVER (ORDER BY pos) AS n
  FROM entries
)
UPDATE "public"."g2p_register_schemas"
SET "filter_schema" = (SELECT jsonb_agg(e ORDER BY n) FROM numbered)::json
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90'
  AND EXISTS (SELECT 1 FROM current);
