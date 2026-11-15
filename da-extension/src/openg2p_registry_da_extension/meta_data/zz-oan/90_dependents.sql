-- Family members / dependents of a development agent, as a list.
--
-- Rows of a child register of DA ("Dependent", purpose TABLE), shown in one
-- section as a table with "Add record", like the education & professional
-- records (80_qualification_list.sql). A row is the family member's name, the
-- relationship to the DA (Master Data list DA_RELATIONSHIP) and, optionally,
-- the date of birth. A DA may have none.
--
-- Whether a dependent was verified is DA Services' matter: it sends a
-- dependent to the registry once it is approved there, so the registry keeps
-- no status.
--
-- Idempotent.
INSERT INTO "public"."g2p_register_definitions" ("register_id","register_mnemonic","register_subject","register_description","master_register_id","register_rank","functional_id_generation_required","register_purpose","program_id","program_mnemonic","register_icon","has_image","dedup_is_enabled","dedup_threshold_score","completion_score_required","outgest_applicable","requires_registrant_authentication","registrant_authentication_validity_days","registrant_re_auth_warning_days_before") VALUES
('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb0','Dependent','Family members / dependents','Family members and dependents of a development agent','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90',20,'FALSE','TABLE',NULL,NULL,NULL,'FALSE','FALSE',0,'FALSE','FALSE','FALSE',730,30)
ON CONFLICT ("register_id") DO UPDATE SET
  "register_mnemonic" = EXCLUDED."register_mnemonic", "register_subject" = EXCLUDED."register_subject",
  "register_description" = EXCLUDED."register_description", "master_register_id" = EXCLUDED."master_register_id",
  "register_purpose" = EXCLUDED."register_purpose";

INSERT INTO "public"."g2p_register_schemas" ("register_id","deduplicate_schema","search_result_schema","filter_schema") VALUES
('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb0','[]','[{"field_name": "member_name", "display_label": "Family Member Name", "order": 1}, {"field_name": "relationship", "display_label": "Relationship", "order": 2}, {"field_name": "date_of_birth", "display_label": "Date Of Birth", "order": 3}]','[]')
ON CONFLICT ("register_id") DO UPDATE SET "search_result_schema" = EXCLUDED."search_result_schema";

INSERT INTO "public"."g2p_register_sections" ("register_id","section_id","section_register_id","is_core_section","section_mnemonic","section_description","documents_required","no_of_verifications_required","is_list","section_weightage","section_ui_schema","cr_auto_approve_for_bene_portal","cr_auto_approve_for_agent_portal","cr_auto_approve_for_staff_portal","cr_auto_approve_for_partner")
SELECT '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','da_dependent_section_06','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb0','FALSE','da_dependent','DA family members and dependents','FALSE',0,'TRUE',0,
jsonb_build_object(
  'section-id', 'da_dependent_section_06',
  'section-title', 'Family members / dependents',
  'section-editable', true,
  'panels', jsonb_build_array(jsonb_build_object('panels', jsonb_build_array(jsonb_build_object('widgets', jsonb_build_array(jsonb_build_object(
    'widget', 'dialog-table', 'widget-id', 'da_dependent_table', 'widget-type', 'dialog-table',
    'widget-label', 'Family members / dependents', 'widget-readonly', false,
    'widget-data-path', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb0.records',
    'widget-data-operations', jsonb_build_object('add', true, 'edit', true, 'remove', true),
    'widget-data-dialog-title-add', 'Add family member / dependent',
    'widget-data-dialog-title-edit', 'Edit family member / dependent',
    'widget-data-columns', jsonb_build_array(
      jsonb_build_object('widget','text','column-key','member_name','widget-type','input','widget-label','Family Member Name','widget-readonly',false,'widget-required',true,'widget-data-path','member_name',
        'widget-data-validation', jsonb_build_object('maxLength', 300)),
      jsonb_build_object('widget','select','column-key','relationship','widget-type','input','widget-label','Relationship','widget-readonly',false,'widget-required',true,'widget-data-path','relationship',
        'widget-data-source', jsonb_build_object('type','api','method','POST','params',jsonb_build_object('page_size',500,'attribute_id','DA_RELATIONSHIP'),'service','attributes','endpoint','values','labelKey','value_display','valueKey','value_id')),
      jsonb_build_object('widget','date','column-key','date_of_birth','widget-type','input','widget-label','Date Of Birth','widget-readonly',false,'widget-required',false,'widget-data-path','date_of_birth',
        'widget-data-format', jsonb_build_object('calendar', 'ethiopic', 'dateFormat', 'DD/MM/YYYY', 'inputMethod', 'picker', 'dateConstraint', 'past-only'),
        'widget-data-options', jsonb_build_object('maxDate', 'today', 'maxDateMessage', 'Enter a date of birth that has passed.'))
    )))))))),
'FALSE','FALSE','FALSE','FALSE' WHERE true
ON CONFLICT ("section_id") DO UPDATE SET "section_ui_schema" = EXCLUDED."section_ui_schema", "is_list" = EXCLUDED."is_list",
  "section_register_id" = EXCLUDED."section_register_id", "section_description" = EXCLUDED."section_description";

INSERT INTO "public"."g2p_register_ui_tab_sections" ("tab_section_id","register_id","tab_id","section_id","section_order") VALUES
('da_tab_section_dependent','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','da_details_tab','da_dependent_section_06',22)
ON CONFLICT ("tab_section_id") DO UPDATE SET "section_order" = EXCLUDED."section_order";

INSERT INTO "public"."g2p_intake_form_ui_tab_sections" ("tab_section_id","tab_id","section_id","section_order") VALUES
('da_intake_section_dependent','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f92','da_dependent_section_06',22)
ON CONFLICT ("tab_section_id") DO UPDATE SET "section_order" = EXCLUDED."section_order";
