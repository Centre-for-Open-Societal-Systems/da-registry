-- Education & professional records of a development agent, as a list.
--
-- A DA can have several records (a degree, another degree, a diploma ...), so
-- they are rows of a child register of DA ("Qualification", purpose TABLE),
-- shown in one section as a table with "Add record", the way the livestock
-- register lists animals. "Add record" opens a dialog with every field:
-- education level, specialisation, position, passout year, joining date and
-- the record's certificates (up to three files of 2 MB each: PDF, JPG, PNG or
-- WebP; the form and the API read these limits from the column below; OAN's table cell widget
-- "oan-file-list-cell", ui/staff-ui/overrides/src/oan/widgets/FileListCellWidget.tsx).
--
-- The one-value section it replaces (da_service_section_02) is taken off the
-- register page and the form. It stays in the metadata as the channel of a
-- file import and a DA Services push, which send one education level,
-- specialisation, position and passout year; the registry turns those into
-- the DA's first row (qualification_sync.py).
--
-- Idempotent.
INSERT INTO "public"."g2p_register_definitions" ("register_id","register_mnemonic","register_subject","register_description","master_register_id","register_rank","functional_id_generation_required","register_purpose","program_id","program_mnemonic","register_icon","has_image","dedup_is_enabled","dedup_threshold_score","completion_score_required","outgest_applicable","requires_registrant_authentication","registrant_authentication_validity_days","registrant_re_auth_warning_days_before") VALUES
('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fa0','Qualification','Education & professional records','Education and professional records of a development agent','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90',10,'FALSE','TABLE',NULL,NULL,NULL,'FALSE','FALSE',0,'FALSE','FALSE','FALSE',730,30)
ON CONFLICT ("register_id") DO UPDATE SET
  "register_mnemonic" = EXCLUDED."register_mnemonic", "register_subject" = EXCLUDED."register_subject",
  "register_description" = EXCLUDED."register_description", "master_register_id" = EXCLUDED."master_register_id",
  "register_purpose" = EXCLUDED."register_purpose";

INSERT INTO "public"."g2p_register_schemas" ("register_id","deduplicate_schema","search_result_schema","filter_schema") VALUES
('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fa0','[]','[{"field_name": "education_level", "display_label": "Education Level", "order": 1}, {"field_name": "specialisation", "display_label": "Specialisation", "order": 2}, {"field_name": "position", "display_label": "Position", "order": 3}, {"field_name": "passout_year", "display_label": "Passout Year", "order": 4}]','[]')
ON CONFLICT ("register_id") DO UPDATE SET "search_result_schema" = EXCLUDED."search_result_schema";

INSERT INTO "public"."g2p_register_sections" ("register_id","section_id","section_register_id","is_core_section","section_mnemonic","section_description","documents_required","no_of_verifications_required","is_list","section_weightage","section_ui_schema","cr_auto_approve_for_bene_portal","cr_auto_approve_for_agent_portal","cr_auto_approve_for_staff_portal","cr_auto_approve_for_partner")
SELECT '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','da_qualification_section_05','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fa0','FALSE','da_qualification','DA education and professional records','FALSE',0,'TRUE',0,
jsonb_build_object(
  'section-id', 'da_qualification_section_05',
  'section-title', 'Education & Professional',
  'section-editable', true,
  'panels', jsonb_build_array(jsonb_build_object('panels', jsonb_build_array(jsonb_build_object('widgets', jsonb_build_array(jsonb_build_object(
    'widget', 'dialog-table', 'widget-id', 'da_qualification_table', 'widget-type', 'dialog-table',
    'widget-label', 'Education & Professional', 'widget-readonly', false, 'widget-required', true,
    'widget-data-path', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fa0.records',
    'widget-data-operations', jsonb_build_object('add', true, 'edit', true, 'remove', true),
    'widget-data-dialog-title-add', 'Add education & professional record',
    'widget-data-dialog-title-edit', 'Edit education & professional record',
    'widget-data-columns', jsonb_build_array(
      jsonb_build_object('widget','select','column-key','education_level','widget-type','input','widget-label','Education Level','widget-readonly',false,'widget-required',true,'widget-data-path','education_level',
        'widget-data-source', jsonb_build_object('type','api','method','POST','params',jsonb_build_object('page_size',500,'attribute_id','DA_EDUCATION_LEVEL'),'service','attributes','endpoint','values','labelKey','value_display','valueKey','value_id')),
      jsonb_build_object('widget','select','column-key','specialisation','widget-type','input','widget-label','Specialisation','widget-readonly',false,'widget-required',true,'widget-data-path','specialisation',
        'widget-data-source', jsonb_build_object('type','api','method','POST','params',jsonb_build_object('page_size',500,'attribute_id','DA_SPECIALISATION'),'service','attributes','endpoint','values','labelKey','value_display','valueKey','value_id')),
      jsonb_build_object('widget','select','column-key','position','widget-type','input','widget-label','Position','widget-readonly',false,'widget-required',true,'widget-data-path','position',
        'widget-data-source', jsonb_build_object('type','api','method','POST','params',jsonb_build_object('page_size',500,'attribute_id','DA_POSITION'),'service','attributes','endpoint','values','labelKey','value_display','valueKey','value_id')),
      jsonb_build_object('widget','number','column-key','passout_year','widget-type','input','widget-label','Passout Year','widget-readonly',false,'widget-required',true,'widget-data-path','passout_year',
        'widget-data-placeholder','Ethiopian calendar year, for example 2010',
        'widget-data-validation', jsonb_build_object('min', 1950, 'max', 2100)),
      jsonb_build_object('widget','date','column-key','joined_date','widget-type','input','widget-label','Joining Date','widget-readonly',false,'widget-required',false,'widget-data-path','joined_date',
        'widget-data-format', jsonb_build_object('calendar', 'ethiopic', 'dateFormat', 'DD/MM/YYYY', 'inputMethod', 'picker', 'dateConstraint', 'past-only'),
        'widget-data-options', jsonb_build_object('maxDate', 'today', 'maxDateMessage', 'Enter a joining date that has passed.')),
      jsonb_build_object('widget','oan-file-list-cell','column-key','certificates','widget-type','input','widget-label','Certificates & documents','widget-readonly',false,'widget-required',false,'widget-data-path','certificates',
        -- The table's popup hands a column to its widget without widget-data-options,
        -- so the file rules have a key of their own, which reaches the widget. The
        -- API reads the same key (g2p_register_domain_service_qualification.py).
        'oan-file-rules', jsonb_build_object('accept','.pdf,.jpg,.jpeg,.png,.webp','maxSize',2097152,'maxFiles',3),
        'widget-data-options', jsonb_build_object('rowLabelColumns', jsonb_build_array('education_level','passout_year')),
        'widget-data-format', jsonb_build_object('pattern', 'Attached'))
    )))))))),
'FALSE','FALSE','FALSE','FALSE' WHERE true
ON CONFLICT ("section_id") DO UPDATE SET "section_ui_schema" = EXCLUDED."section_ui_schema", "is_list" = EXCLUDED."is_list",
  "section_register_id" = EXCLUDED."section_register_id", "section_description" = EXCLUDED."section_description";

-- One section on the page and on the form: the list takes the old section's place.
DELETE FROM "public"."g2p_register_ui_tab_sections" WHERE "tab_section_id" = 'da_tab_section_service';
DELETE FROM "public"."g2p_intake_form_ui_tab_sections" WHERE "tab_section_id" = 'da_intake_section_service';

INSERT INTO "public"."g2p_register_ui_tab_sections" ("tab_section_id","register_id","tab_id","section_id","section_order") VALUES
('da_tab_section_qualification','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','da_details_tab','da_qualification_section_05',20)
ON CONFLICT ("tab_section_id") DO UPDATE SET "section_order" = EXCLUDED."section_order";

INSERT INTO "public"."g2p_intake_form_ui_tab_sections" ("tab_section_id","tab_id","section_id","section_order") VALUES
('da_intake_section_qualification','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f92','da_qualification_section_05',20)
ON CONFLICT ("tab_section_id") DO UPDATE SET "section_order" = EXCLUDED."section_order";

-- The one-value section stays the channel of a file import, a DA Services push
-- and a change request that names one education level, specialisation and
-- position. It gains the passout year, required like the other three, so those
-- channels are refused without it as the form is.
UPDATE "public"."g2p_register_sections" s
SET "section_ui_schema" = jsonb_set(
      s."section_ui_schema"::jsonb,
      '{panels,0,panels,0,widgets}',
      COALESCE((
        SELECT jsonb_agg(w ORDER BY ord)
        FROM jsonb_array_elements(s."section_ui_schema"::jsonb #> '{panels,0,panels,0,widgets}') WITH ORDINALITY AS x(w, ord)
        WHERE w ->> 'widget-id' IS DISTINCT FROM 'passout_year'), '[]'::jsonb)
      || jsonb_build_array(jsonb_build_object(
        'widget', 'number', 'widget-id', 'passout_year', 'widget-type', 'input',
        'widget-label', 'Passout Year', 'widget-readonly', false, 'widget-required', true,
        'widget-data-path', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.passout_year')))
WHERE s."section_id" = 'da_service_section_02'
  AND s."section_ui_schema"::jsonb #>> '{panels,0,panels,0,panel-id}' = 'panel_da_education';

-- Its name in a refusal ("Required: Education & Professional: fill in ...") is
-- the name staff know the section by.
UPDATE "public"."g2p_register_sections" s
SET "section_ui_schema" = jsonb_set(s."section_ui_schema"::jsonb, '{section-title}', '"Education & Professional"'::jsonb)
WHERE s."section_id" = 'da_service_section_02'
  AND s."section_ui_schema"::jsonb ->> 'section-title' IS DISTINCT FROM 'Education & Professional';
