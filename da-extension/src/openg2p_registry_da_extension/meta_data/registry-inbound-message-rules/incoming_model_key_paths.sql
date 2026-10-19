-- DA (Development Agent) register: file import (CSV / XLSX) through the
-- platform's import pipeline. Edit here, keep it idempotent.

-- The import worker wraps each row as
--   {"headers": {"message_id", "sender_id", "signature"}, "body": <row>}
-- sender_id is checked against Partner Management when it is configured;
-- without it (local stack) any sender is accepted.
INSERT INTO "public"."incoming_model_key_paths" ("key_path_id","data_model_id","key_path_for_message_id","key_path_for_sender","key_path_for_signature","key_path_for_signature_payload","is_list","key_path_for_list_elements") VALUES
('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb3','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb2','$.headers.message_id','$.headers.sender_id','$.headers.signature','$.body','FALSE','$.body')
ON CONFLICT ("key_path_id") DO NOTHING;

-- DA Services request body: {"header": {"message_id", "sender_id", "data_model", ...},
-- "signature", "message": {...}} (docs/da-services-api-contract.md).
INSERT INTO "public"."incoming_model_key_paths" ("key_path_id","data_model_id","key_path_for_message_id","key_path_for_sender","key_path_for_signature","key_path_for_signature_payload","is_list","key_path_for_list_elements") VALUES
('6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb6','6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb5','$.body.header.message_id','$.body.header.sender_id','$.body.signature','$.body[''header'',''message'']','FALSE','$.body.message')
ON CONFLICT ("key_path_id") DO NOTHING;
