-- Home address of a development agent, in the contact section.
--
-- "Work location" (Region, Zone, Woreda, Kebele) is where the DA works. Where
-- the DA lives is one line of free text, up to 100 characters, kept in the
-- platform's own address_line_1 column, so no column is added. It is
-- optional: records saved before it, file imports and DA Services pushes have
-- none. The API applies the same limit (g2p_register_domain_service_da.py).
--
-- The address has the full width under the phone and email columns: next to
-- them, as one more column, the record page cut it off after a few words and
-- squeezed the others. A section lays its top panels side by side, so the two
-- rows sit in one vertical panel.
--
-- Idempotent: the phone and email row is looked up by its id wherever it is,
-- and the layout is rebuilt around it each time.
UPDATE "public"."g2p_register_sections" s
SET "section_ui_schema" = jsonb_set(
      jsonb_set(s."section_ui_schema"::jsonb, '{section-title}', '"Contact details and home address"'),
      '{panels}',
      jsonb_build_array(jsonb_build_object(
        'panel-id', 'da_contact_layout',
        'panel-orientation', 'vertical',
        'panels', jsonb_build_array(
          jsonb_path_query_first(s."section_ui_schema"::jsonb, '$.** ? (@."panel-id" == "da_contact_row")'),
          jsonb_build_object(
            'panel-id', 'da_home_address_row',
            'panel-orientation', 'vertical',
            'widgets', jsonb_build_array(jsonb_build_object(
              'widget', 'text',
              'widget-id', 'address_line_1',
              'widget-type', 'input',
              'widget-label', 'Home address',
              'widget-required', false,
              'widget-data-path', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.address_line_1',
              'widget-data-validation', jsonb_build_object('maxLength', 100)
            ))
          )
        )
      ))
    ),
    "section_description" = 'Contact details and home address'
WHERE s."section_id" = 'da_contact_section_04'
  AND jsonb_path_exists(s."section_ui_schema"::jsonb, '$.** ? (@."panel-id" == "da_contact_row")');
