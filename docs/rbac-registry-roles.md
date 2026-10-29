# DA Services roles in the DA registry (DA-165, DA-166)

This page covers what a DA Services user can do in the DA registry staff API,
and which DAs they can see.

- **What they can do** comes from registry roles. These are Keycloak client
  roles on `da-registry-staff-portal`.
- **Which DAs they see** comes from data policies. A data policy is a filter on
  DA records, held as a client role `DP_<mnemonic>`.

## 1. Roles (DA-165)

Each DA Services role is a Keycloak group in the `staff` realm. A user joins the
group of their role, and the group carries the registry roles.
`docker/local-dev/keycloak-init.sh` creates these groups on the local stack.

| DA Services role (group) | Registry roles |
|---|---|
| `DA Services - Development Agent` | Data Editor |
| `DA Services - Supervisor` | Intake Officer, Intake Validator, Data Editor, Data Validator, Data Supervisor |
| `DA Services - Executive` | Data Supervisor |
| `DA Services - OAN Administrator` | Operations Administrator + all Supervisor roles |
| `DA Services - Communications Officer` | none (no registry access) |

These are the staff API calls DA Services uses, with the permission each one
needs:

| Staff API call | Permission |
|---|---|
| `register-data/search_in_a_register`, `get_subject_record` | `register:view` |
| `intake-form-data/save_intake_form_submission`, `finalize_...`, `search_in_intake_form_submissions` | `intakeSubmission:edit` |
| `change-requests/create_change_request` | `changeRequest:create` |
| `change-requests/search_in_change_request` | `changeRequest:view` |
| `register-data/get_export_queue_records` (the register list screen polls it) | `register:export` |

### Who approves a DA

Every submitted DA and every change request goes through the platform's
two-level approval: Stage 1 Officers, then Stage 2 Officers. Each stage is
completed by any one of its approvers (mode `any-n`, one decision). The
repository seeds the same approvers in every OAN registry (`awe_meta_data/`):
Stage 1 = `alex.carter` or `admin`, Stage 2 = `nina.patel` or `admin`; the two
officers are created by `docker/local-dev/keycloak-init.sh`.

Who approves in a real environment is configuration, not code (decision of
27-28 Oct 2026, Faiz / Asmit): after deployment an administrator edits the
two DA policies in the AWE admin portal and replaces the example users, for
instance with a `role` rule (a Keycloak client role such as Operations
Administrator or Intake Validator on `da-registry-staff-portal`; AWE's service
account needs `view-users` and `view-clients`) or with named users. Routing a
Woreda's submissions to its own supervisor (DA-33) is the same kind of
configuration once the approver roles exist per Woreda.

Bulk import (file) and the DA Services push go through the same two stages.
The worker has no user token, so it opens the approval request with a Keycloak
client-credentials token (`DA_AWE_TOKEN_URL`, `DA_AWE_CLIENT_ID`,
`DA_AWE_CLIENT_SECRET`; by default the process's Master Data client
`da-registry-backend`), see `register_domain/services/awe_service_token.py`.
Imports are approved manually, like every other record; no setting approves
them automatically, and no role (the Operations Administrator included)
approves a submission or a change request directly: the direct-approval
endpoints answer `AWE_APPROVAL_REQUIRED`. Decision (23 Oct 2026, Faiz and
Shikha).

## 3. Local test result (16 Oct 2026)

The local stack had 604 DAs. Test users were put one per group; the Supervisor
was scoped to Woreda ET010101 and the Executive to Region ET04.

| User | Search DAs | DA in ET010101 | DA in ET040301 | Submissions | Start form | Change requests |
|---|---|---|---|---|---|---|
| Development Agent | 604 | allow | allow | 403 | 403 | allow |
| Supervisor (ET010101) | 43 | allow | REG-ERR-012 | 58 of 588 | allow | 4 (all in ET010101) |
| Executive (ET04) | 109 | REG-ERR-012 | allow | 403 | 403 | 0 |
| OAN Administrator | 604 | allow | allow | 588 | allow | 4 |
| Communications Officer | 403 | 403 | 403 | 403 | 403 | 403 |

## 4. Limits and open points

- **A Development Agent sees only their own record** when their token carries
  the claim `da_id` (section 5). Without that claim a Development Agent can
  read every DA; use the claim, or a narrow data policy.
- **Login:** these roles work with a staff Keycloak token. How DA Services
  users sign in (OAN auth service or Keycloak) is still open (DA-167).
- **Approver routing:** who approves a Woreda's submissions is the approval
  workflow's job (DA-33), not the data policies'.
- A Woreda code is unique, but Woreda names are not (23 names repeat). Always
  scope by code.

## 5. A Development Agent's own record (self-service)

A DA signs in to DA Services (or the registry portal) with their own Keycloak
user and may read and change only their own DA record. This is enforced in the
registry's staff API (`register_domain/services/da_own_record.py`), so it holds
for DA Services, the registry portal and any direct API call alike:

- The Keycloak user carries the attribute `da_id` = the DA's DA-ID
  (for example `DA-4374521939`). The client scope `da-self-service` maps it
  into the access token as the claim `da_id` (local: `keycloak-init.sh`; on a
  shared Keycloak: create the scope with a *User Attribute* mapper
  `da_id -> da_id`, make it a default scope of the clients a DA signs in with,
  and set the realm's user profile *unmanaged attributes* to `Admin can edit`).
- When the token has `da_id` and the user's only roles on
  `da-registry-staff-portal` are the Development Agent ones (`Data Editor`,
  plus any `DP_` data-policy role), the request's data policies are replaced
  by one ALLOW policy `functional_record_id = <da_id>` on the DA register.
  DA search, DA details, tab records and change-request reads then return
  only that record; any other record answers `REG-ERR-012 RECORD_ACCESS_DENIED`.
- `create_change_request` is checked separately (the platform does not put it
  under data policies): the change must target the DA's own record and one
  of the sections contact (`da_contact_section_04`), service
  (`da_service_section_02`) or location (`da_location_section_03`). The
  identity section (name, Fayda ID) answers `REG-ERR-012`.
- The DA's change request goes through the same two-level approval as any
  other; the DA cannot approve it.
- A user with any wider role (Intake Officer, Validator, Supervisor,
  Operations Administrator, ...) is not restricted by this rule, whatever
  claims the token has.

Local test (26 Oct 2026): user `da.test` (Data Editor, `da_id` DA-4374521939)
saw 1 of 50 DAs, read and changed only its own contact section, was refused
on another record and on its identity section; `admin` was unchanged.

Settings: `DA_SELF_SERVICE_CLAIM` (default `da_id`),
`DA_SELF_SERVICE_CLIENT_ID` (default `da-registry-staff-portal`).
