-- Date of birth is one date field on the same Ethiopian calendar picker as
-- every other date in the OAN registries (98_ethiopian_dates.sql sets the
-- calendar), in place of the two number boxes for the month and year of birth.
-- It is the platform's own birth_date column. The server fills birth_month_ec
-- and birth_year_ec from it on save, so imports that carry only the month and
-- year, the DCI output and reports keep working, and records saved before this
-- change keep their month and year.
--
-- The date is required unless the record already has a year of birth: DA
-- Services pushes and file imports send only the month and year, and the
-- required check (required_fields.py) reads the same "require" action.
CREATE OR REPLACE FUNCTION pg_temp.da_birth_date(node jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  result jsonb;
BEGIN
  IF jsonb_typeof(node) = 'array' THEN
    SELECT COALESCE(jsonb_agg(
             CASE WHEN value ->> 'widget-id' = 'birth_month_ec' THEN
               jsonb_build_object(
                 'widget', 'date', 'widget-id', 'birth_date', 'widget-type', 'input',
                 'widget-label', 'Date of birth',
                 'widget-data-path', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.birth_date',
                 'widget-required', false,
                 'widget-data-format', jsonb_build_object(
                   'dateFormat', 'DD/MM/YYYY', 'inputMethod', 'picker', 'dateConstraint', 'past-only'),
                 'widget-data-options', jsonb_build_object(
                   'minDate', '1927-09-12', 'maxDate', 'today',
                   'minDateMessage', 'Enter a date of birth in 1920 of the Ethiopian calendar or later.',
                   'maxDateMessage', 'Enter a date of birth that has passed.',
                   'actions', jsonb_build_array(jsonb_build_object(
                     'action', 'require',
                     'condition', jsonb_build_object(
                       'field', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.birth_year_ec',
                       'operator', 'empty')))))
             ELSE pg_temp.da_birth_date(value) END ORDER BY ord), '[]'::jsonb)
      INTO result
    FROM jsonb_array_elements(node) WITH ORDINALITY AS a(value, ord)
    WHERE value ->> 'widget-id' IS DISTINCT FROM 'birth_year_ec';
  ELSIF jsonb_typeof(node) = 'object' THEN
    SELECT COALESCE(jsonb_object_agg(key, pg_temp.da_birth_date(value)), '{}'::jsonb)
      INTO result FROM jsonb_each(node);
  ELSE
    result := node;
  END IF;
  RETURN result;
END $$;

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = pg_temp.da_birth_date("section_ui_schema")
WHERE "section_id" = 'da_identity_section_01';

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM "public"."g2p_register_sections"
             WHERE jsonb_path_exists("section_ui_schema",
               'lax $.** ? (@."widget-id" == "birth_month_ec" || @."widget-id" == "birth_year_ec")')) THEN
    RAISE EXCEPTION 'The month and year of birth are still number boxes on a DA form';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM "public"."g2p_register_sections"
                 WHERE "section_id" = 'da_identity_section_01'
                   AND jsonb_path_exists("section_ui_schema",
                     'lax $.** ? (@."widget-id" == "birth_date" && @.widget == "date")')) THEN
    RAISE EXCEPTION 'The DA identity section has no date of birth field';
  END IF;
END $$;
