-- The DA's location section is where the DA works, not where they live: the
-- heading says so, on the form and on the record page.
UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(section_ui_schema::text, '"section-title": "Location"', '"section-title": "Work location"')::jsonb
WHERE "section_id" = 'da_location_section_03';

UPDATE "public"."g2p_register_sections" SET "section_description" = 'Work location' WHERE "section_id" = 'da_location_section_03';

-- How far down the Work location goes depends on the position (decision of
-- 18 Nov 2026, location_depth.py):
--
--   Development agent, Senior DA          Region, Zone, Woreda and Kebele
--   Supervisor, Executive officer         Region, Zone and Woreda
--   Admin, Communication officer          no Work location
--
-- The rule is the geo widget's "oan-location-depth": a level per position
-- ("none": no Work location), and "default" for a position not named. The
-- form shows the levels down to the position's one and no Work location for
-- "none" (ui/staff-ui/overrides/src/oan/widgets/GeoByPositionWidget.tsx); the
-- server reads the same key as the widget's hide and require actions
-- (required_fields.py), for the form, a file import and a DA Services push.
-- What goes deeper than the position's level is left out, not refused: a
-- Kebele given for a supervisor, a location given for an administrator.
--
-- The widget carries no show / hide / require actions of its own: the
-- platform form applies only the last of several, and this rule needs more
-- than one value. A record without a position yet takes "default", so the
-- location stays required.
--
-- Idempotent: the widget's flag, options and rule are set, whatever they were.
UPDATE "public"."g2p_register_sections" s
SET "section_ui_schema" = jsonb_set(jsonb_set(jsonb_set(s."section_ui_schema"::jsonb,
      '{panels,0,panels,0,widgets,0,widget-required}', 'false'::jsonb),
      '{panels,0,panels,0,widgets,0,widget-data-options}', '{}'::jsonb),
      '{panels,0,panels,0,widgets,0,oan-location-depth}',
      jsonb_build_object(
        'field', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.position',
        'levels', jsonb_build_object(
          'DEVELOPMENT_AGENT', 'kebele', 'SENIOR_DA', 'kebele',
          'SUPERVISOR', 'woreda', 'EXECUTIVE_OFFICER', 'woreda',
          'ADMIN', 'none', 'COMMUNICATION_OFFICER', 'none'),
        'default', 'kebele'))
WHERE s."section_id" = 'da_location_section_03'
  AND s."section_ui_schema"::jsonb #>> '{panels,0,panels,0,widgets,0,widget-id}' = 'da_geo_hierarchy';
