-- Education records of a development agent, as a list.
--
-- A person can have several (a degree, another degree, a diploma ...), so they
-- are rows of a child register of DA ("Qualification", purpose TABLE), shown
-- in one section as a table with "Add record", the way the livestock register
-- lists animals. "Add record" opens a dialog with the record's fields:
-- education level, passout year and its certificates (up to three files of
-- 2 MB each: PDF, JPG, PNG or WebP; the form and the API read these limits
-- from the column below; OAN's table cell widget "oan-file-list-cell",
-- ui/staff-ui/overrides/src/oan/widgets/FileListCellWidget.tsx).
--
-- Position, specialisation and joining date are not part of an education
-- record: a person holds one position. They are fields of the DA record, in
-- the "Position and reporting" section (85_position_and_reporting.sql).
--
-- Who needs an education record is said on the table: it is required while
-- the record's position is a development agent's. Other positions (supervisor,
-- officer, administrator) may have none. The form's submit check and the
-- import read the same two "require" actions (required_fields.py).
--
-- Idempotent.
INSERT INTO "public"."g2p_register_definitions" ("register_id","register_mnemonic","register_subject","register_description","master_register_id","register_rank","functional_id_generation_required","register_purpose","program_id","program_mnemonic","register_icon","has_image","dedup_is_enabled","dedup_threshold_score","completion_score_required","outgest_applicable","requires_registrant_authentication","registrant_authentication_validity_days","registrant_re_auth_warning_days_before") VALUES
('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fa0','Qualification','Education records','Education records of a development agent','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90',10,'FALSE','TABLE',NULL,NULL,NULL,'FALSE','FALSE',0,'FALSE','FALSE','FALSE',730,30)
ON CONFLICT ("register_id") DO UPDATE SET
  "register_mnemonic" = EXCLUDED."register_mnemonic", "register_subject" = EXCLUDED."register_subject",
  "register_description" = EXCLUDED."register_description", "master_register_id" = EXCLUDED."master_register_id",
  "register_purpose" = EXCLUDED."register_purpose";

INSERT INTO "public"."g2p_register_schemas" ("register_id","deduplicate_schema","search_result_schema","filter_schema") VALUES
('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fa0','[]','[{"field_name": "education_level", "display_label": "Education Level", "order": 1}, {"field_name": "passout_year", "display_label": "Passout Year", "order": 2}]','[]')
ON CONFLICT ("register_id") DO UPDATE SET "search_result_schema" = EXCLUDED."search_result_schema";

INSERT INTO "public"."g2p_register_sections" ("register_id","section_id","section_register_id","is_core_section","section_mnemonic","section_description","documents_required","no_of_verifications_required","is_list","section_weightage","section_ui_schema","cr_auto_approve_for_bene_portal","cr_auto_approve_for_agent_portal","cr_auto_approve_for_staff_portal","cr_auto_approve_for_partner")
SELECT '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','da_qualification_section_05','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fa0','FALSE','da_qualification','DA education records','FALSE',0,'TRUE',0,
jsonb_build_object(
  'section-id', 'da_qualification_section_05',
  'section-title', 'Education',
  'section-editable', true,
  'panels', jsonb_build_array(jsonb_build_object('panels', jsonb_build_array(jsonb_build_object('widgets', jsonb_build_array(jsonb_build_object(
    'widget', 'dialog-table', 'widget-id', 'da_qualification_table', 'widget-type', 'dialog-table',
    'widget-label', 'Education', 'widget-readonly', false, 'widget-required', false,
    -- Required while the record's position is a development agent's.
    'widget-data-options', jsonb_build_object('actions', jsonb_build_array(
      jsonb_build_object('action', 'require', 'condition', jsonb_build_object(
        'field', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.position', 'operator', 'equals', 'value', 'DEVELOPMENT_AGENT')),
      jsonb_build_object('action', 'require', 'condition', jsonb_build_object(
        'field', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.position', 'operator', 'equals', 'value', 'SENIOR_DA')))),
    'widget-data-path', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fa0.records',
    'widget-data-operations', jsonb_build_object('add', true, 'edit', true, 'remove', true),
    'widget-data-dialog-title-add', 'Add education record',
    'widget-data-dialog-title-edit', 'Edit education record',
    'widget-data-columns', jsonb_build_array(
      jsonb_build_object('widget','select','column-key','education_level','widget-type','input','widget-label','Education Level','widget-readonly',false,'widget-required',true,'widget-data-path','education_level',
        'widget-data-source', jsonb_build_object('type','api','method','POST','params',jsonb_build_object('page_size',500,'attribute_id','DA_EDUCATION_LEVEL'),'service','attributes','endpoint','values','labelKey','value_display','valueKey','value_id')),
      jsonb_build_object('widget','number','column-key','passout_year','widget-type','input','widget-label','Passout Year','widget-readonly',false,'widget-required',true,'widget-data-path','passout_year',
        'widget-data-placeholder','Ethiopian calendar year, for example 2010',
        'widget-data-validation', jsonb_build_object('min', 1950, 'max', 2100)),
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

INSERT INTO "public"."g2p_register_ui_tab_sections" ("tab_section_id","register_id","tab_id","section_id","section_order") VALUES
('da_tab_section_qualification','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','da_details_tab','da_qualification_section_05',20)
ON CONFLICT ("tab_section_id") DO UPDATE SET "section_order" = EXCLUDED."section_order";

INSERT INTO "public"."g2p_intake_form_ui_tab_sections" ("tab_section_id","tab_id","section_id","section_order") VALUES
('da_intake_section_qualification','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f92','da_qualification_section_05',20)
ON CONFLICT ("tab_section_id") DO UPDATE SET "section_order" = EXCLUDED."section_order";
