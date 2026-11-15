-- Profile photo of a development agent, in the Personal details section.
--
-- The photo is kept the platform's way: the file goes to the document store
-- (bucket "documents"), and the record holds its id in
-- record_image_document_id, the field the register list shows as the record's
-- picture. The platform reads the photo's link into record_image_url.
--
-- The widget package uploads a section's photo, and sets
-- record_image_document_id, only for widgets of type "header-section". The
-- platform's own header widget also shows the record's id, status and dates,
-- which have no place on a form, so "widget-variant" selects OAN's photo
-- picker (ui/staff-ui/overrides/src/oan/widgets/ProfilePhotoWidget.tsx):
-- choose or take a photo, see it, replace or remove it. It scales the photo
-- to 1024 px before upload and refuses one over 2 MB.
--
-- The photo is optional. A file import or a DA Services push carries no photo;
-- it is added on the form or later with Edit details.
--
-- Idempotent: the panel is taken out and put back as the first panel of the
-- section's row each time.
UPDATE "public"."g2p_register_sections" s
SET "section_ui_schema" = jsonb_set(
      s."section_ui_schema"::jsonb,
      '{panels,0,panels}',
      jsonb_build_array(jsonb_build_object(
        'panel-id', 'panel_da_photo',
        'panel-title', 'Photo',
        'panel-orientation', 'vertical',
        'widgets', jsonb_build_array(jsonb_build_object(
          'widget', 'header-section',
          'widget-variant', 'oan-profile-photo',
          'widget-id', 'da_photo',
          'widget-type', 'group',
          'widget-label', 'Photo',
          'widget-readonly', false,
          'widget-required', false,
          'widget-data-path', jsonb_build_object(
            'image', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.record_image_document_id',
            'imageUrl', '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90.record_image_url'),
          'widget-data-format', jsonb_build_object('imageSize', 160, 'maxDimension', 1024, 'jpegQuality', 0.85),
          'widget-data-validation', jsonb_build_object('maxSizeKb', 2048)))))
      || COALESCE((
        SELECT jsonb_agg(panel ORDER BY ord)
        FROM jsonb_array_elements(s."section_ui_schema"::jsonb #> '{panels,0,panels}') WITH ORDINALITY AS p(panel, ord)
        WHERE panel ->> 'panel-id' IS DISTINCT FROM 'panel_da_photo'), '[]'::jsonb))
WHERE s."section_id" = 'da_identity_section_01'
  AND s."section_ui_schema"::jsonb #>> '{panels,0,panel-id}' = 'da_identity_row';

DO $$
BEGIN
  IF (SELECT count(*) FROM "public"."g2p_register_sections" s,
             jsonb_path_query(s."section_ui_schema"::jsonb, 'strict $.** ? (@."widget-id" == "da_photo")') w
      WHERE s."section_id" = 'da_identity_section_01'
        AND w ->> 'widget' = 'header-section' AND w ->> 'widget-variant' = 'oan-profile-photo') <> 1 THEN
    RAISE EXCEPTION 'The DA Personal details section must have exactly one profile photo widget';
  END IF;
END $$;
