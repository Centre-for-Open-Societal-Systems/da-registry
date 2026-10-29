-- Readable text: the last pass over what staff read in the Development agent registry.
--
-- Plain English in sentence case, with no abbreviation that is not spelled out
-- (ID, FAN and GPS stay; DA becomes development agent, EC and GC become the
-- calendar they stand for). Only display text changes; ids, codes, mnemonics
-- and the import template's column headings do not. Every statement is an
-- explicit-id UPDATE or a merge of named translation keys, so it is
-- idempotent. It sorts after 10_label_casing.sql and so wins over it;
-- 30_readable_text_checks.sql fails the seed if a visible label, message or
-- choice reads like a code.

UPDATE "public"."registry_languages"
SET "domain_translation" = (COALESCE("domain_translation"::jsonb, '{}'::jsonb) ||
'{
 "da_details": "Development agent details",
 "da": "Development agents",
 "functional_record_id": "Development agent ID",
 "farmer_registry": "Development agent registry",
 "birth_date": "Date of birth (Gregorian calendar)",
 "birth_date_ec": "Date of birth (Ethiopian calendar)",
 "birth_month_ec": "Month of birth (Ethiopian calendar)",
 "birth_year_ec": "Year of birth (Ethiopian calendar)",
 "first_name": "Name",
 "middle_name": "Father''s name",
 "last_name": "Grandfather''s name",
 "is_psnp_user": "Productive Safety Net Programme beneficiary",
 "enumerator_gps": "Enumerator GPS location"
}'::jsonb)::json
WHERE "language_code" = 'en';

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(replace(replace(section_ui_schema::text, '"section-title": "DA record"', '"section-title": "Development agent record"'), '"panel-title": "DA record"', '"panel-title": "Development agent record"'), '"widget-label": "DA-ID"', '"widget-label": "Development agent ID"')::jsonb
WHERE "section_id" = 'da_record_section_00';

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(section_ui_schema::text, '"section-title": "Education & professional"', '"section-title": "Education and profession"')::jsonb
WHERE "section_id" = 'da_service_section_02';

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(section_ui_schema::text, '"section-title": "Geographic location"', '"section-title": "Location"')::jsonb
WHERE "section_id" = 'da_location_section_03';

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(replace(section_ui_schema::text, '"patternMessage": "Ethiopian phone number, e.g. 0911234567"', '"patternMessage": "Enter an Ethiopian phone number, for example 0911234567."'), '"patternMessage": "Enter a valid email address"', '"patternMessage": "Enter a valid email address."')::jsonb
WHERE "section_id" = 'da_contact_section_04';

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(replace(replace(replace(replace(replace(section_ui_schema::text, '"widget-label": "Father name"', '"widget-label": "Father''s name"'), '"widget-label": "Grandfather name"', '"widget-label": "Grandfather''s name"'), '"widget-label": "Month of birth (EC)"', '"widget-label": "Month of birth (Ethiopian calendar)"'), '"widget-label": "Year of birth (EC)"', '"widget-label": "Year of birth (Ethiopian calendar)"'), '"patternMessage": "Use letters (Latin or Ethiopic), spaces, hyphens and apostrophes only"', '"patternMessage": "Use letters (Latin or Ethiopic), spaces, hyphens and apostrophes only."'), '"patternMessage": "Fayda ID (FAN) must be exactly 16 digits"', '"patternMessage": "Enter the Fayda ID (FAN) as exactly 16 digits."')::jsonb
WHERE "section_id" = 'da_identity_section_01';

UPDATE "public"."g2p_register_schemas"
SET "search_result_schema" = replace("search_result_schema"::jsonb::text, '"display_label": "DA-ID"', '"display_label": "Development agent ID"')::json
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90';

UPDATE "public"."g2p_register_schemas"
SET "filter_schema" = replace(replace(replace(replace("filter_schema"::jsonb::text, '"display_label": "Kebele id"', '"display_label": "Kebele ID"'), '"label": "Masters"', '"label": "Master''s degree"'), '"label": "Senior DA"', '"label": "Senior development agent"'), '"label": "CSV import"', '"label": "File import"')::json
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90';

UPDATE "public"."g2p_register_sections" SET "section_description" = 'Development agent record' WHERE "section_id" = 'da_record_section_00';

UPDATE "public"."g2p_register_sections" SET "section_description" = 'Education and profession' WHERE "section_id" = 'da_service_section_02';

UPDATE "public"."g2p_register_sections" SET "section_description" = 'Contact details' WHERE "section_id" = 'da_contact_section_04';

UPDATE "public"."g2p_register_sections" SET "section_description" = 'Location' WHERE "section_id" = 'da_location_section_03';

UPDATE "public"."g2p_register_sections" SET "section_description" = 'Personal details' WHERE "section_id" = 'da_identity_section_01';

UPDATE "public"."g2p_intake_form_ui_tabs" SET "tab_label" = 'Development agent registration' WHERE "tab_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f92';
UPDATE "public"."g2p_intake_form_definitions" SET "form_description" = 'Development agent registration' WHERE "form_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91';
UPDATE "public"."g2p_register_definitions" SET "register_description" = 'Development agents: the extension workers and their identity' WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90';
UPDATE "public"."g2p_registry_configuration" SET "registry_name" = 'Development agent registry' WHERE "registry_name" = 'DA Registry';
