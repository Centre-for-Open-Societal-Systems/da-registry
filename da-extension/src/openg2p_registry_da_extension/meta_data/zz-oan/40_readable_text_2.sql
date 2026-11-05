-- Readable text, second pass: what the first audit after 20_readable_text.sql
-- still found. Display text only; ids, codes, mnemonics and the location
-- code filters (DA Services lists a woreda's development agents through
-- region_code, zone_code and woreda_code) are untouched.
--
-- Every statement is an explicit-id UPDATE or a merge of named translation
-- keys, so it is idempotent. It sorts after 30_readable_text_checks.sql.

-- Widget labels and validation messages, one targeted replacement per widget key
UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(replace(replace(section_ui_schema::text,
  '"widget-label": "Alternate number"', '"widget-label": "Other phone number"'),
  '"widget-label": "Alternate Number"', '"widget-label": "Other phone number"'),
  '"widget-label": "Telegram Number"', '"widget-label": "Telegram number"')::jsonb
WHERE "section_id" = 'da_contact_section_04';

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(replace(replace(replace(section_ui_schema::text,
  '"widget-label": "Joining date"', '"widget-label": "Date joined"'),
  '"widget-label": "Joining Date"', '"widget-label": "Date joined"'),
  '"widget-label": "Source"', '"widget-label": "Registered through"'),
  '"section-title": "Education and profession"', '"section-title": "Education and position"')::jsonb
WHERE "section_id" = 'da_service_section_02';

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(replace(section_ui_schema::text,
  '"widget-label": "Region / zone / Woreda / Kebele"', '"widget-label": "Region, zone, woreda and kebele"'),
  '"widget-label": "Region / Zone / Woreda / Kebele"', '"widget-label": "Region, zone, woreda and kebele"')::jsonb
WHERE "section_id" = 'da_location_section_03';

-- The birth month and year say their limits where the form checks them
-- (the widgets are found by widget-id, so the other keys of each rule stay)
UPDATE "public"."g2p_register_sections" s
SET "section_ui_schema" = (
  SELECT jsonb_set(s."section_ui_schema", '{panels}', (
    SELECT jsonb_agg(jsonb_set(row_panel, '{panels}', (
      SELECT jsonb_agg(jsonb_set(panel, '{widgets}', (
        SELECT jsonb_agg(
          CASE w ->> 'widget-id'
            WHEN 'birth_month_ec' THEN jsonb_set(w, '{widget-data-validation}',
              COALESCE(w -> 'widget-data-validation', '{}'::jsonb) || jsonb_build_object(
                'minMessage', 'Enter a birth month from 1 to 13.', 'maxMessage', 'Enter a birth month from 1 to 13.'))
            WHEN 'birth_year_ec' THEN jsonb_set(w, '{widget-data-validation}',
              COALESCE(w -> 'widget-data-validation', '{}'::jsonb) || jsonb_build_object(
                'minMessage', 'Enter a birth year of 1920 or later, in the Ethiopian calendar.'))
            ELSE w END ORDER BY wo)
        FROM jsonb_array_elements(panel -> 'widgets') WITH ORDINALITY AS x(w, wo)
      ) ) ORDER BY po)
      FROM jsonb_array_elements(row_panel -> 'panels') WITH ORDINALITY AS y(panel, po)
    )) ORDER BY ro)
    FROM jsonb_array_elements(s."section_ui_schema" -> 'panels') WITH ORDINALITY AS z(row_panel, ro)
  )))
WHERE s."section_id" = 'da_identity_section_01';

-- Section names the server messages use are the section titles
UPDATE "public"."g2p_register_sections" SET "section_description" = 'Education and position' WHERE "section_id" = 'da_service_section_02';

-- Search list and filters: one wording for the Fayda ID
UPDATE "public"."g2p_register_schemas"
SET "search_result_schema" = replace("search_result_schema"::jsonb::text, '"display_label": "Fayda ID"', '"display_label": "Fayda ID (FAN)"')::json
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90';

UPDATE "public"."g2p_register_schemas"
SET "filter_schema" = replace(replace(replace(replace("filter_schema"::jsonb::text,
  '"display_label": "Fayda ID"', '"display_label": "Fayda ID (FAN)"'),
  '"display_label": "Region code"', '"display_label": "Region code (Master Data)"'),
  '"display_label": "Zone code"', '"display_label": "Zone code (Master Data)"'),
  '"display_label": "Woreda code"', '"display_label": "Woreda code (Master Data)"')::json
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90';

-- The intake form reads as a sentence, not a code
UPDATE "public"."g2p_intake_form_definitions" SET "form_mnemonic" = 'Development agent registration' WHERE "form_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91';

-- Display text for codes and statuses that lists, history and tasks show
UPDATE "public"."registry_languages"
SET "domain_translation" = (COALESCE("domain_translation"::jsonb, '{}'::jsonb) ||
'{
 "country": "Country",
 "region": "Region",
 "zone": "Zone",
 "woreda": "Woreda",
 "kebele": "Kebele",
 "DEVELOPMENT_AGENT": "Development agent",
 "SENIOR_DA": "Senior development agent",
 "SENIOR_DEVELOPMENT_AGENT": "Senior development agent",
 "MALE": "Male",
 "FEMALE": "Female",
 "SINGLE": "Single",
 "MARRIED": "Married",
 "WIDOWED": "Widowed",
 "DIVORCED": "Divorced",
 "SEPARATED": "Separated",
 "CERTIFICATE": "Certificate",
 "DIPLOMA": "Diploma",
 "DEGREE": "Bachelor''s degree",
 "MASTERS": "Master''s degree",
 "LIVESTOCK": "Livestock",
 "OTHER": "Other",
 "UNKNOWN": "Unknown",
 "MR": "Mr",
 "MRS": "Mrs",
 "MISS": "Miss",
 "MS": "Ms",
 "DR": "Dr",
 "CROP_PRODUCTION": "Crop production",
 "NATURAL_RESOURCES": "Natural resources",
 "AGRONOMY": "Agronomy",
 "HORTICULTURE": "Horticulture",
 "WEB_INTAKE": "Web intake",
 "CSV_IMPORT": "File import",
 "INTAKE_FORM": "Intake form",
 "FINAL": "Submitted",
 "DRAFT": "Draft",
 "PENDING": "Pending approval",
 "APPROVED": "Approved",
 "REJECTED": "Rejected",
 "PROCESSED": "Done",
 "FAILED": "Failed",
 "NOT_APPLICABLE": "Not applicable",
 "PARTNER": "Imported from another system",
 "STAFF_PORTAL": "Staff portal",
 "PARTNER_STAFF_PORTAL": "Staff portal",
 "PARTNER_DA_SERVICES": "Development agent services",
 "DA_SERVICES": "Development agent services feed",
 "IMPORT_FILE": "File import",
 "completed": "Done",
 "skipped": "Closed by another approver",
 "in_review-stage1": "In review (first approval)",
 "in_review-stage2": "In review (second approval)"
}'::jsonb)::json
WHERE "language_code" = 'en';

-- The education filter says what the Master Data list says
UPDATE "public"."g2p_register_schemas"
SET "filter_schema" = replace("filter_schema"::jsonb::text, '"label": "Degree"', '"label": "Bachelor''s degree"')::json
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90';
