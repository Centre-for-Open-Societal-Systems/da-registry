-- Every number widget, including table columns, is right-aligned and grouped
-- with ","; the type, places and minimum each one declares are kept.
CREATE OR REPLACE FUNCTION pg_temp.oan_number_format(node jsonb)
RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE
  result jsonb;
BEGIN
  IF jsonb_typeof(node) = 'array' THEN
    SELECT COALESCE(jsonb_agg(pg_temp.oan_number_format(value) ORDER BY ord), '[]'::jsonb)
      INTO result FROM jsonb_array_elements(node) WITH ORDINALITY AS a(value, ord);
  ELSIF jsonb_typeof(node) = 'object' THEN
    SELECT COALESCE(jsonb_object_agg(key, pg_temp.oan_number_format(value)), '{}'::jsonb)
      INTO result FROM jsonb_each(node);
    IF node->>'widget' = 'number' THEN
      result := jsonb_set(result, '{widget-data-format}',
        COALESCE(result->'widget-data-format', '{}'::jsonb) || '{"textAlign":"right","thousandSeparator":","}'::jsonb);
    END IF;
  ELSE
    result := node;
  END IF;
  RETURN result;
END $$;

UPDATE public.g2p_register_sections
SET section_ui_schema = pg_temp.oan_number_format(section_ui_schema)
WHERE section_ui_schema IS NOT NULL
  AND section_ui_schema::text LIKE '%"widget": "number"%';
