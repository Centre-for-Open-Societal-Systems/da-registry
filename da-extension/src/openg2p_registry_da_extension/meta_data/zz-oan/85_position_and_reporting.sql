-- Position and reporting of a person in the DA register: position,
-- specialisation, joining date and the person they report to.
--
-- A person holds one position, so these are fields of the DA record itself,
-- not of an education record (80_qualification_list.sql). The section is the
-- register's one-value section da_service_section_02, back on the register
-- page and on the form with a new title and new fields.
--
-- Position decides what else is asked:
--   - Specialisation is shown, and required, for a development agent and a
--     senior DA. The platform's conditions hold one value each and the last
--     rule wins, so there are two select widgets on the same field, one per
--     position; at most one is on screen.
--   - "Reports to" is required of everyone but the administrator, who reports
--     to no one: the field is hidden for that position. It holds the DA-ID of
--     a person in this register, chosen from a list (OAN widget
--     "oan-reports-to", ui/staff-ui/overrides/src/oan/widgets/ReportsToWidget.tsx).
--     A file import or a DA Services push without it, or with a DA-ID no one
--     has, is refused and stays in the exceptions list; it does not go to
--     approval (decision of 18 Nov 2026).
-- The API reads the same conditions (required_fields.py) and empties a field
-- the form hides (g2p_register_domain_service_da.py).
--
-- Who may give or change a position is OFF for now (decision of 18 Nov 2026,
-- for the team demo on dev): anyone who can fill in the form may give any
-- position, and a file import or a DA Services push may bring any position.
-- The rules exist (position_rights.py, ui/staff-ui/overrides/src/oan/widgets/
-- SelectByRightWidget.tsx) and are switched on by putting these keys back:
--   on the Position widget ("widget": "oan-select-by-right"):
--     'oan-value-rights', jsonb_build_object(
--       'open', jsonb_build_array('DEVELOPMENT_AGENT', 'SENIOR_DA'),
--       'roles', jsonb_build_array('Operations Administrator'),
--       'permission', 'incomingMessage:view'),
--     'oan-change-roles', jsonb_build_array('Intake Officer', 'Data Supervisor', 'Operations Administrator'),
--   on the Reports to widget:
--     'oan-change-roles', jsonb_build_array('Intake Officer', 'Data Supervisor', 'Operations Administrator'),
-- See docs/rbac-registry-roles.md section 6.
--
-- Layout: position, specialisation and joining date on the left; on the right
-- the person reported to, with their name and position under the DA-ID. The
-- three labels on the right all begin "Reports to" ("Reports to (ID)", "(name)",
-- "(position)"), so a second "Name" and "Position" are not read as the
-- record's own. A label does not say "DA" (30_readable_text_checks.sql).
--
-- The section comes before Education on the form: whether an education record
-- is needed depends on the position.
--
-- Idempotent: the section's schema is written whole each time.
WITH parts AS (
  SELECT
    -- Left: what the person does.
    jsonb_build_object(
      'panel-id', 'panel_da_position', 'panel-title', 'Position', 'panel-orientation', 'vertical',
      'widgets', jsonb_build_array(
        jsonb_build_object(
          'widget', 'select', 'widget-id', 'position', 'widget-type', 'input',
          'widget-label', 'Position', 'widget-readonly', false, 'widget-required', true,
          'widget-data-path', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.position',
          'widget-data-source', jsonb_build_object('type','api','method','POST','params',jsonb_build_object('page_size',500,'attribute_id','DA_POSITION'),'service','attributes','endpoint','values','labelKey','value_display','valueKey','value_id')),
        jsonb_build_object(
          'widget', 'select', 'widget-id', 'specialisation', 'widget-type', 'input',
          'widget-label', 'Specialisation', 'widget-readonly', false, 'widget-required', true,
          'widget-data-path', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.specialisation',
          'widget-data-options', jsonb_build_object('actions', jsonb_build_array(jsonb_build_object(
            'action', 'show', 'condition', jsonb_build_object(
              'field', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.position', 'operator', 'equals', 'value', 'DEVELOPMENT_AGENT')))),
          'widget-data-source', jsonb_build_object('type','api','method','POST','params',jsonb_build_object('page_size',500,'attribute_id','DA_SPECIALISATION'),'service','attributes','endpoint','values','labelKey','value_display','valueKey','value_id')),
        jsonb_build_object(
          'widget', 'select', 'widget-id', 'specialisation_senior_da', 'widget-type', 'input',
          'widget-label', 'Specialisation', 'widget-readonly', false, 'widget-required', true,
          'widget-data-path', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.specialisation',
          'widget-data-options', jsonb_build_object('actions', jsonb_build_array(jsonb_build_object(
            'action', 'show', 'condition', jsonb_build_object(
              'field', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.position', 'operator', 'equals', 'value', 'SENIOR_DA')))),
          'widget-data-source', jsonb_build_object('type','api','method','POST','params',jsonb_build_object('page_size',500,'attribute_id','DA_SPECIALISATION'),'service','attributes','endpoint','values','labelKey','value_display','valueKey','value_id')),
        jsonb_build_object(
          'widget', 'date', 'widget-id', 'joined_date', 'widget-type', 'input',
          'widget-label', 'Joining date', 'widget-readonly', false, 'widget-required', false,
          'widget-data-path', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.joined_date',
          'widget-data-format', jsonb_build_object('calendar', 'ethiopic', 'dateFormat', 'DD/MM/YYYY', 'inputMethod', 'picker', 'dateConstraint', 'past-only'),
          'widget-data-options', jsonb_build_object('maxDate', 'today', 'maxDateMessage', 'Enter a joining date that has passed.')))) AS position_panel,
    -- Right: the person they report to.
    jsonb_build_object(
      'panel-id', 'panel_da_reports_to', 'panel-title', 'Reports to', 'panel-orientation', 'vertical',
      'widgets', jsonb_build_array(
        jsonb_build_object(
          'widget', 'oan-reports-to', 'widget-id', 'reports_to', 'widget-type', 'input',
          'widget-label', 'Reports to (ID)', 'widget-readonly', false, 'widget-required', true,
          'widget-data-path', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.reports_to',
          'widget-data-options', jsonb_build_object('actions', jsonb_build_array(jsonb_build_object(
            'action', 'hide', 'condition', jsonb_build_object(
              'field', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.position', 'operator', 'equals', 'value', 'ADMIN')))),
          -- What the list in the popup reads: this register, ten people at a
          -- time, and the Master Data list its position filter offers.
          'oan-lookup', jsonb_build_object(
            'register_id', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90', 'page_size', 10, 'position_attribute', 'DA_POSITION')))) AS reports_to_panel
)
UPDATE "public"."g2p_register_sections" s
SET "section_ui_schema" = jsonb_build_object(
      'section-id', COALESCE(s."section_ui_schema"::jsonb ->> 'section-id', 'da_service'),
      'section-title', 'Position and reporting',
      'section-editable', true,
      'panels', jsonb_build_array(jsonb_build_object(
        'panel-id', 'da_professional_row',
        'panel-orientation', 'horizontal',
        'panels', jsonb_build_array(parts.position_panel, parts.reports_to_panel)))),
    "section_description" = 'Position and reporting'
FROM parts
WHERE s."section_id" = 'da_service_section_02';

-- On the register page and on the form, between the contact details and the
-- education records.
INSERT INTO "public"."g2p_register_ui_tab_sections" ("tab_section_id","register_id","tab_id","section_id","section_order") VALUES
('da_tab_section_service','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','da_details_tab','da_service_section_02',17)
ON CONFLICT ("tab_section_id") DO UPDATE SET "section_order" = EXCLUDED."section_order", "section_id" = EXCLUDED."section_id";

INSERT INTO "public"."g2p_intake_form_ui_tab_sections" ("tab_section_id","tab_id","section_id","section_order") VALUES
('da_intake_section_service','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f92','da_service_section_02',17)
ON CONFLICT ("tab_section_id") DO UPDATE SET "section_order" = EXCLUDED."section_order", "section_id" = EXCLUDED."section_id";
