-- Fails the seed when text staff read looks like a code or shorthand.
--
-- Every label, placeholder, help text, section title, validation message and
-- choice of the sections a tab or the intake form shows is resolved the way
-- the staff UI resolves it (the language's domain translation, then core's,
-- else the string itself). It must not hold an underscore, be an ALL-CAPS code,
-- or use the shorthand DA, EC or GC, which are spelled out. The search and
-- filter labels get the same test.

DO $$
DECLARE
  found text;
BEGIN
  SELECT string_agg(DISTINCT s.section_id || ': ' || v.txt, '; ') INTO found
  FROM "public"."g2p_register_sections" s
  CROSS JOIN LATERAL jsonb_path_query(s.section_ui_schema, 'strict $.**') n
  CROSS JOIN LATERAL jsonb_each_text(
    CASE WHEN jsonb_typeof(n) = 'object' THEN n ELSE '{}'::jsonb END) kv
  CROSS JOIN LATERAL (
    SELECT COALESCE(NULLIF(l."domain_translation"::jsonb ->> kv.value, ''),
                    NULLIF(l."core_translation"::jsonb ->> kv.value, ''), kv.value) AS txt
    FROM "public"."registry_languages" l WHERE l."is_default") v
  WHERE (s.section_id IN (SELECT section_id FROM "public"."g2p_register_ui_tab_sections")
         OR s.section_id IN (SELECT section_id FROM "public"."g2p_intake_form_ui_tab_sections"))
    AND kv.key IN ('widget-label', 'widget-data-placeholder', 'widget-data-helptext', 'widget-data-add-label',
                   'section-title', 'panel-title', 'patternMessage', 'minMessage', 'label', 'title')
    AND (v.txt ~ '_' OR v.txt ~ '^[A-Z][A-Z0-9 /-]{3,}$' OR v.txt ~ '\m(DA|EC|GC)\M');
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'Text staff read looks like a code or shorthand: %', found;
  END IF;

  SELECT string_agg(DISTINCT x, '; ') INTO found
  FROM "public"."g2p_register_schemas" d
  CROSS JOIN LATERAL (
    SELECT jsonb_path_query(COALESCE(d.search_result_schema::jsonb, 'null'::jsonb), 'lax $[*].display_label') #>> '{}' AS x
    UNION ALL
    SELECT jsonb_path_query(COALESCE(d.filter_schema::jsonb, 'null'::jsonb), 'lax $[*].display_label') #>> '{}'
    UNION ALL
    SELECT jsonb_path_query(COALESCE(d.filter_schema::jsonb, 'null'::jsonb), 'lax $[*].options_source[*].label') #>> '{}'
  ) t
  WHERE x ~ '_' OR x ~ '^[A-Z][A-Z0-9 /-]{3,}$' OR x ~ '\m(DA|EC|GC)\M';
  IF found IS NOT NULL THEN
    RAISE EXCEPTION 'A search or filter label looks like a code or shorthand: %', found;
  END IF;

  IF EXISTS (SELECT 1 FROM "public"."g2p_intake_form_ui_tabs" t WHERE t."tab_label" ~ '\m(DA|EC|GC)\M' OR t."tab_label" ~ '_')
     OR EXISTS (SELECT 1 FROM "public"."registry_languages" l
                WHERE l."is_default" AND (l."domain_translation"::jsonb ->> 'da_details') ~ '\m(DA|EC|GC)\M') THEN
    RAISE EXCEPTION 'A tab label looks like a code or shorthand';
  END IF;
END $$;
