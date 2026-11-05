-- DA (Development Agent) register: file import (CSV / XLSX) through the
-- platform's import pipeline. Edit here, keep it idempotent.

-- Template: templates/import_file_to_openg2p_da.json.j2
INSERT INTO "public"."incoming_templates" ("template_id","register_id","data_model_id","template_document_id","jsonld_expansion_required","created_at","updated_at") VALUES
('IN-TMPL-DA-IMPORT','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb2','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fa1','FALSE','2026-10-05 00:00:00',NULL)
ON CONFLICT ("template_id") DO UPDATE SET "template_document_id" = EXCLUDED."template_document_id";

-- DA Services uses the same template: its enricher returns the same DA fields.
INSERT INTO "public"."incoming_templates" ("template_id","register_id","data_model_id","template_document_id","jsonld_expansion_required","created_at","updated_at") VALUES
('IN-TMPL-DA-SERVICES','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb5','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fa1','FALSE','2026-10-06 00:00:00',NULL)
ON CONFLICT ("template_id") DO UPDATE SET "template_document_id" = EXCLUDED."template_document_id";
