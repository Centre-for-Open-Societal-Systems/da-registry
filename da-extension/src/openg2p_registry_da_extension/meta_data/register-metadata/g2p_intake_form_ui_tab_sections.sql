-- DA (Development Agent) register metadata, field list agreed with the team (Oct 2026).
-- Edit here, keep it idempotent.

INSERT INTO "public"."g2p_intake_form_ui_tab_sections" ("tab_section_id","tab_id","section_id","section_order") VALUES
('da_intake_section_identity','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f92','da_identity_section_01',10),
('da_intake_section_contact','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f92','da_contact_section_04',15),
('da_intake_section_service','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f92','da_service_section_02',20),
('da_intake_section_location','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f92','da_location_section_03',30)
ON CONFLICT ("tab_section_id") DO UPDATE SET
    "tab_id" = EXCLUDED."tab_id",
    "section_id" = EXCLUDED."section_id",
    "section_order" = EXCLUDED."section_order";
