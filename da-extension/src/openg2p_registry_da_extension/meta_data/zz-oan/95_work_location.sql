-- The DA's location section is where the DA works, not where they live: the
-- heading says so, on the form and on the record page.
UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(section_ui_schema::text, '"section-title": "Location"', '"section-title": "Work location"')::jsonb
WHERE "section_id" = 'da_location_section_03';

UPDATE "public"."g2p_register_sections" SET "section_description" = 'Work location' WHERE "section_id" = 'da_location_section_03';
