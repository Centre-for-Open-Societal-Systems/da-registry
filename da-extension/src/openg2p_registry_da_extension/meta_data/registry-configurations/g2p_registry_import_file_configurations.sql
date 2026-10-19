-- DA (Development Agent) register: file import (CSV / XLSX) through the
-- platform's import pipeline. Edit here, keep it idempotent.

-- Shown in the staff portal under New Intake > Import from file.
INSERT INTO "public"."g2p_registry_import_file_configurations" ("import_file_configuration_id","register_id","form_id","data_model_id","import_file_template_mnemonic","import_file_template_description") VALUES
('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb1','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb2','DA Import','Development Agents from a CSV or Excel (.xlsx) file')
ON CONFLICT ("import_file_configuration_id") DO UPDATE SET
    "import_file_template_mnemonic" = EXCLUDED."import_file_template_mnemonic",
    "import_file_template_description" = EXCLUDED."import_file_template_description";
