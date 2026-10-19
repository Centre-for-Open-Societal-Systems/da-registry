-- DA (Development Agent) register: file import (CSV / XLSX) through the
-- platform's import pipeline. Edit here, keep it idempotent.

-- An import already names the register and intake form, so the patterns are
-- not evaluated; the row is still looked up by (register, form, data model).
INSERT INTO "public"."incoming_model_semantic_patterns" ("semantic_pattern_id","data_model_id","register_id","intake_form_id","section_id","pattern_for_register","pattern_for_intake_form","pattern_for_section","key_path_for_business_payload","raw_payload_enricher_class") VALUES
('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb0','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb2','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91',NULL,NULL,'$.headers.sender_id=>^Staff Portal$',NULL,'$.body','DAImportFileEnricherService')
ON CONFLICT ("semantic_pattern_id") DO UPDATE SET
    "key_path_for_business_payload" = EXCLUDED."key_path_for_business_payload",
    "raw_payload_enricher_class" = EXCLUDED."raw_payload_enricher_class";

-- DA Services: the request names DA and the DA intake form in its header; the
-- business payload is `message`, read by DAServicesEnricherService.
INSERT INTO "public"."incoming_model_semantic_patterns" ("semantic_pattern_id","data_model_id","register_id","intake_form_id","section_id","pattern_for_register","pattern_for_intake_form","pattern_for_section","key_path_for_business_payload","raw_payload_enricher_class") VALUES
('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb7','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb5','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91',NULL,'$.body.header.data_model=>^DA_SERVICES$','$.body.header.data_model=>^DA_SERVICES$',NULL,'$.body.message','DAServicesEnricherService')
ON CONFLICT ("semantic_pattern_id") DO UPDATE SET
    "key_path_for_business_payload" = EXCLUDED."key_path_for_business_payload",
    "raw_payload_enricher_class" = EXCLUDED."raw_payload_enricher_class";
