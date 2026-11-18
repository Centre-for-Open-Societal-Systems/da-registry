-- The DA's location section is where the DA works, not where they live: the
-- heading says so, on the form and on the record page.
UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(section_ui_schema::text, '"section-title": "Location"', '"section-title": "Work location"')::jsonb
WHERE "section_id" = 'da_location_section_03';

UPDATE "public"."g2p_register_sections" SET "section_description" = 'Work location' WHERE "section_id" = 'da_location_section_03';

-- Work location is required of everyone but the administrator, who heads the
-- programme and works at no one Kebele (decision of 18 Nov 2026). For an
-- administrator it may be filled or left empty. The rule is a "require" action
-- on the widget, read by the form and by the API (required_fields.py); a file
-- import and a DA Services push follow it too. A record without a position
-- yet counts as not an administrator, so the location stays required.
--
-- Idempotent: the widget's flag and options are set, whatever they were.
UPDATE "public"."g2p_register_sections" s
SET "section_ui_schema" = jsonb_set(
      jsonb_set(s."section_ui_schema"::jsonb, '{panels,0,panels,0,widgets,0,widget-required}', 'false'::jsonb),
      '{panels,0,panels,0,widgets,0,widget-data-options}',
      jsonb_build_object('actions', jsonb_build_array(jsonb_build_object(
        'action', 'require', 'condition', jsonb_build_object(
          'field', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.position', 'operator', 'notEquals', 'value', 'ADMIN')))))
WHERE s."section_id" = 'da_location_section_03'
  AND s."section_ui_schema"::jsonb #>> '{panels,0,panels,0,widgets,0,widget-id}' = 'da_geo_hierarchy';
