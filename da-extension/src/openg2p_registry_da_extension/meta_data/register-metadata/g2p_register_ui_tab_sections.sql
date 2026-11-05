-- DA (Development Agent) register metadata, field list agreed with the team (Oct 2026).
-- Edit here, keep it idempotent.

INSERT INTO "public"."g2p_register_ui_tab_sections" ("tab_section_id","register_id","tab_id","section_id","section_order") VALUES
('da_tab_section_record','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','da_details_tab','da_record_section_00',5),
('da_tab_section_identity','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','da_details_tab','da_identity_section_01',10),
('da_tab_section_contact','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','da_details_tab','da_contact_section_04',15),
('da_tab_section_service','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','da_details_tab','da_service_section_02',20),
('da_tab_section_location','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','da_details_tab','da_location_section_03',25)
ON CONFLICT ("tab_section_id") DO UPDATE SET
    "register_id" = EXCLUDED."register_id",
    "tab_id" = EXCLUDED."tab_id",
    "section_id" = EXCLUDED."section_id",
    "section_order" = EXCLUDED."section_order";
