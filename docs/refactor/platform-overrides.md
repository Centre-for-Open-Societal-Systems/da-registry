# DA registry: everything that touches the platform

Yash Sontakke · 28 October 2026 · registry-platform `1.2.2-rc.557`, branch `feature/da-on-refactor`

What Aruna asked for on 27 October: one list of every place where the DA
extension overrides, wraps or otherwise depends on the OpenG2P platform's
internals, so that a platform upgrade (or an upstream fix) tells us what to
re-check or remove. No platform image or file is patched; everything below
lives inside the extension (`da-extension/src/openg2p_registry_da_extension/`)
and is installed at start-up by `app.py`. Each entry is idempotent (a marker
stops a double install) and covered by a unit test that skips when the
platform is not importable.

How to use this file: on every platform version bump, run the extension's
tests inside the new images (section "Re-check on upgrade"), then walk the
table; when an upstream fix lands, delete the entry and its code.

## 1. Platform bugs worked around (should go upstream, then be deleted)

| # | Where | Platform anchor | What it does | Why | Upstream status |
|---|---|---|---|---|---|
| P1 | `platform_overrides.py` `install_partner_json_responses` | `openg2p_registry_partner_api...RequestResponseHelper._construct_data_model_response` (replaced) | serialises the partner ingest response with `model_dump(mode="json")` | every `POST /partner/ingest_data` answered HTTP 500 (`datetime` not JSON serialisable); seen on rc.544 and rc.557, came back in livestock when its patch was dropped | not reported yet |
| P2 | `platform_overrides.py` `install_scoped_permission_lookup` | `iam_core...ResolvePermissionMiddleware.dispatch` and `_fetch_permissions_for_roles` (wrapped) | resolves a user's permissions for this registry's own IAM application only (`/user-access/get_application_permissions_for_user?application_mnemonic=<client>`) | IAM matched role names across every registry on the shared Keycloak, so a farmer-registry role could grant DA permissions and vice versa | not reported yet |
| P3 | `platform_overrides.py` `install_worker_null_pool` (installed on the Celery `worker_process_init` signal in `__init__.py`) | `openg2p_registry_celery_worker.engine.Engine.get_async_engine` (replaced) | builds the worker's async engine with `NullPool` | asyncpg "Task attached to a different loop" in forked worker processes; the error still shows on first attempts on rc.557 (rows are retried and complete), so the fix is partial (finding B3 in `pr8-validation-da.md`) | not reported yet |
| P4 | `app.py` `_patch_filter_builder` | `openg2p_registry_core.services.filter_builder.FilterBuilder._validate_value` and `_build_field_conditions` (wrapped) | accepts `"true"` / `"false"` strings for boolean filters | the staff UI sends booleans as strings and the platform rejects them | not reported yet |

## 2. DA behaviour the platform has no hook for (overrides by design; candidates for platform features)

| # | Where | Platform anchor | What it does | Why | If the platform changes |
|---|---|---|---|---|---|
| D1 | `register_domain/services/da_intake_guard.py` `install_da_intake_guard` | subclass of `G2PIntakeFormDataService`, instance inserted at the front of `openg2p_fastapi_common.context.component_registry`; overrides `save_intake_form_submission_with_session` and `finalize_submission_with_session`; uses `_get_section_or_error`, `_records_for_validation`, `_get_submission_or_error`, `_resolve_intake_form_class`, `_get_intake_rows`, `_get_form_sections`, `_build_section_payloads` | required fields (metadata `widget-required`) checked for a new record on save and for the whole submission on finalize | the platform validates only the fields a request carries and nothing at finalize; an empty submission reached the approvers | this is the pattern Asmit asked for (subclass ahead in the registry). Suggest upstream: run the required-widget check at finalize in the platform. If the private helpers are renamed, the subclass fails at call time; the unit test `test_required_fields.py::TestGuard` catches the override points |
| D2 | `register_domain/services/auto_approve.py` `install_da_auto_approve` | `G2PAweIntegrationService.start_intake_submission_workflow` (wrapped) | file imports and DA Services pushes (no user token) start the approval workflow with the worker's Keycloak service token (`awe_service_token.py`); optional auto-approve of unique DAs (`DA_AUTO_APPROVE_IMPORTS`, default off) | the platform starts an approval only with a user's bearer token; unattended ingestion had none, so imports were silently left PENDING with no task | wrap. Suggest upstream: a service-token path for unattended submissions. Align env names with the farmer extension's `REGISTRY_CELERY_WORKERS_AWE_*` |
| D3 | `register_domain/services/da_own_record.py` `install_da_own_record_guard` | `iam_core.user_auth.middleware.data_policy.DataPolicyMiddleware.dispatch` (wrapped) and `G2PRegisterChangerequestControllerService.create_change_request` (wrapped) | a token with claim `da_id` (a Development Agent) sees and edits only their own record: a synthetic data policy `functional_record_id = da_id` on reads, and change requests only on that record and only in the contact / service / location sections | the platform's data policies are role-based lists, not per-user; no hook on change-request creation | wraps. Suggest upstream: per-user (claim-based) data policies. `install` raises if `create_change_request` disappears, so an upgrade fails loudly |
| D4 | `register_domain/services/g2p_register_domain_service_da.py` | `G2PRegisterDomainService` subclass registered through `G2PRegisterDomainFactory` (the platform's own extension point) | DA validation (Fayda FAN, phones, email, EC dates, one DA per Fayda, flattened geo names/codes) | normal extension code | supported hook; nothing to re-check beyond the tests |
| D5 | `ingestion_pipeline/enricher_services/` | `G2PPayloadEnricherInterface` (the platform's own extension point) | Excel/CSV rows and DA Services messages → DA fields | normal extension code | supported hook |

## 3. Platform internals read without wrapping (break only if the platform renames them)

| # | Where | What is used | Why |
|---|---|---|---|
| R1 | `ingestion_pipeline/enricher_services/code_lists.py` | `G2PAttributeValueValidator.field_map_from_ui_schema` (platform helper, public classmethod) and the Master Data tables `g2p_attributes` / `g2p_attribute_values` (read through the worker's Master Data DB settings when present, the Master Data API otherwise) | the list each dropdown uses and its values, so imports accept exactly what the form accepts |
| R2 | `ingestion_pipeline/enricher_services/g2p_da_enricher_services.py` `_MasterDataGeo` | Master Data tables `g2p_geo_levels` / `g2p_geo_level_values` read directly (worker DB settings) | Kebele lookup by name or id for imports. The platform's geo service looks units up by id only. Dev also configures the DB; if Master Data ever becomes API-only, switch this to the API like `code_lists.py` |
| R3 | `register_domain/services/required_fields.py` | model `G2PRegisterSection.section_ui_schema` and the widget keys `widget-required`, `widget-label`, `widget-data-path` | required fields from the metadata (single source for the UI and the server) |
| R4 | `partner_api/da_status_controller.py`, `register_domain/services/push_status.py`, `exceptions.py` | ingestion tables `incoming_raw_data`, `incoming_classified_data`, `incoming_enriched_transformed_data`, `g2p_intake_form_submissions` read by SQL | `GET /partner/da/status` and `/exceptions` for DA Services |
| R5 | `platform_overrides.py`, `da_own_record.py`, `auto_approve.py` | `openg2p_registry_core.config.Settings` prefixes (`REGISTRY_STAFF_PORTAL_API_`, `REGISTRY_PARTNER_API_`, `REGISTRY_CELERY_WORKERS_`) and rc.557 setting names (`..._DCI_ALLOWED_SEARCH_FIELDS`, `..._VALIDATE_ATTRIBUTE_VALUES`, `..._AWE_*`, `..._MASTER_DATA_*`) | configuration; rc.544 → rc.557 already renamed one of them (`DCI_EXPRESSION_ALLOWED_FIELDS`) |
| R6 | `meta_data/`, `awe_meta_data/` seeds | platform tables and the register-metadata JSON shapes (`widget-data-source` type `api` / service `attributes`, `filter_schema`, `search_result_schema`), AWE tables `approval_policy` / `approval_stage` / `approver_rule` | configuration; every INSERT has `ON CONFLICT` so a re-seed on a new platform is safe |
| R7 | `ui/staff-ui/` | upstream staff-ui pinned by commit in `deps.json`; `overrides/` is empty | no UI override today. Known platform-UI issue, not fixed here: Next on a section with nothing entered makes no request but shows "Saved"; the server refuses the incomplete save/submit, so no bad data |

## 4. Re-check on upgrade

1. Bump `RP_VERSION` (Dockerfiles, `Jenkinsfile`, `helm/.../Chart.yaml`), build the images.
2. In each image run the extension tests: `python -m pytest /app/da-extension/tests` (staff-api runs all; partner-api `test_platform_overrides.py`, `test_push_status.py`, `test_code_lists.py`; worker `test_platform_overrides.py`, `test_awe_service_token.py`, `test_auto_approve.py`, `test_import_enricher.py`, `test_da_services_enricher.py`, `test_code_lists.py`). A missing anchor fails or skips there.
3. Start the stack and read the start-up logs: each `install_*` logs once; `install_da_own_record_guard` raises if its anchor is gone.
4. Re-run the validation list in `pr8-validation-da.md` (form → two-stage approval → DA-ID; change request; search filters; partner push; DCI; import; UI).
5. For every entry in section 1, check the platform's release notes: if the bug is fixed, delete the override and its test.
