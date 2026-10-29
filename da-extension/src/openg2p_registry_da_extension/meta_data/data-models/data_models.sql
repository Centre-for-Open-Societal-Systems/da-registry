-- Every data model answers with the DCI response template. Without a template
-- the Partner API cannot serialise its reply (the header carries a datetime),
-- answers 500, and the sender resends the same record. The rows are upserted
-- on the mnemonic because rows created earlier kept an empty template and
-- ON CONFLICT DO NOTHING would never repair them.
INSERT INTO "public"."data_models" ("data_model_id","data_model_mnemonic","pattern_for_data_model","response_template_document_id","is_active") VALUES
('c331ba96-ac35-4014-9d13-4ef327f6b79b','DCI','*','1f0953d4-f0fb-4336-a126-4d0519a74ffc','TRUE')
ON CONFLICT ("data_model_mnemonic") DO UPDATE SET "response_template_document_id" = EXCLUDED."response_template_document_id";

-- DCI response template: dci_commons_response.json.j2

-- File import (CSV / XLSX). The import worker always names this model, so
-- the pattern is only there because the column is NOT NULL.
INSERT INTO "public"."data_models" ("data_model_id","data_model_mnemonic","pattern_for_data_model","response_template_document_id","is_active") VALUES
('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb2','IMPORT_FILE','$.data_model=>^IMPORT_FILE$','1f0953d4-f0fb-4336-a126-4d0519a74ffc','TRUE')
ON CONFLICT ("data_model_mnemonic") DO UPDATE SET "response_template_document_id" = EXCLUDED."response_template_document_id";

-- DA Services (Frappe) pushing DAs it has approved, through the partner API
-- (POST /partner/ingest_data?data_model=DA_SERVICES). The pattern lets the
-- partner API detect it when the query parameter is left out.
INSERT INTO "public"."data_models" ("data_model_id","data_model_mnemonic","pattern_for_data_model","response_template_document_id","is_active") VALUES
('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb5','DA_SERVICES','$.body.header.data_model=>^DA_SERVICES$','1f0953d4-f0fb-4336-a126-4d0519a74ffc','TRUE')
ON CONFLICT ("data_model_mnemonic") DO UPDATE SET "response_template_document_id" = EXCLUDED."response_template_document_id";
