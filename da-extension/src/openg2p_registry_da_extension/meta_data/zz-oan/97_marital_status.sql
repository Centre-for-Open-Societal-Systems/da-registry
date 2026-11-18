-- Marital status: optional, from the DA's own Master Data list.
--
-- The common MARITAL_STATUS list ends with "Unknown", which became the easy
-- answer for a field nobody needs to fill. The DA registry reads its own list
-- DA_MARITAL_STATUS instead (openg2p-data: the same values without Unknown),
-- and the field is optional: a status nobody knows is left empty (decision of
-- 18 Nov 2026). The form, the API and a file import or push read the list and
-- the flag from here (choice_check.py, code_lists.py, required_fields.py).
--
-- Idempotent: the widget whose id is marital_status gets the list and the flag.
CREATE OR REPLACE FUNCTION pg_temp.da_marital_status(node jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  result jsonb;
BEGIN
  IF jsonb_typeof(node) = 'array' THEN
    SELECT COALESCE(jsonb_agg(pg_temp.da_marital_status(value) ORDER BY ord), '[]'::jsonb)
      INTO result FROM jsonb_array_elements(node) WITH ORDINALITY AS a(value, ord);
  ELSIF jsonb_typeof(node) = 'object' THEN
    SELECT COALESCE(jsonb_object_agg(key, pg_temp.da_marital_status(value)), '{}'::jsonb)
      INTO result FROM jsonb_each(node);
    IF result ->> 'widget-id' = 'marital_status' THEN
      result := jsonb_set(result, '{widget-required}', 'false'::jsonb);
      result := jsonb_set(result, '{widget-data-source,params,attribute_id}', '"DA_MARITAL_STATUS"'::jsonb);
    END IF;
  ELSE
    result := node;
  END IF;
  RETURN result;
END $$;

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = pg_temp.da_marital_status("section_ui_schema"::jsonb)
WHERE "section_id" = 'da_identity_section_01';
