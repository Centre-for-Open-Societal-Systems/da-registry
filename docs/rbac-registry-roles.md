# DA Services roles in the DA registry

This page covers what a DA Services user can do in the DA registry staff API,
and which DAs they can see.

- **What they can do** comes from registry roles. These are Keycloak client
  roles on `da-registry-staff-portal`.
- **Which DAs they see** comes from data policies. A data policy is a filter on
  DA records, held as a client role `DP_<mnemonic>`.

## 1. Roles

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
| `da/get_push_status`, `da/search_exceptions` (DA extension: status of a push, exceptions list) | `incomingMessage:view` (Operations Administrator, Integration Manager) |

### Who approves a DA

Every submitted DA (web form, file import, DA Services push) goes through the
platform's two-level approval: first approval, then second approval. A change
to an existing DA is not approved in the registry, see "Changes to a DA"
below. Each stage is
completed by any one of its approvers (mode `any-n`, one decision). The
repository seeds the same approvers in every OAN registry (`awe_meta_data/`):
first approval = `alex.carter` or `admin`, second approval = `nina.patel` or `admin`; the two
officers are created by `docker/local-dev/keycloak-init.sh`.

Who approves in a real environment is configuration, not code (decision of
27-28 Oct 2026, Faiz / Asmit): after deployment an administrator edits the
two DA policies in the AWE admin portal and replaces the example users, for
instance with a `role` rule (a Keycloak client role such as Operations
Administrator or Intake Validator on `da-registry-staff-portal`; AWE's service
account needs `view-users` and `view-clients`) or with named users. Routing a
Woreda's submissions to its own supervisor is the same kind of
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

### Changes to a DA

A change to an existing DA (contact, qualification, identity or location) is
made in DA Services and approved there twice, by the Supervisor and then by the
Administrator. DA Services then sends the change request to the registry with
the approving Administrator's token, and the registry applies it at once: both
stages of the policy `registry.change_request.da` carry `skip_if` = always true
(`awe_meta_data/20_approval_stage.sql`), so the workflow engine approves the
request when it is created (events `stage_skipped`, `stage_skipped`,
`request_approved`) and the registry applies it through the usual callback.
Decision of 12 Nov 2026 (Shikha): one approval path, in DA Services, and the
signed-in user's token, no service account for now.

What the registry still does for every change request: the format and list
checks (16-digit Fayda ID, phone, email, coded values), one DA per Fayda ID,
the register history, and, after a location change, the Region / Zone / Woreda
/ Kebele names and codes are derived again from the new Kebele.

What it no longer does: check who asked for the change. **Anyone who holds
`changeRequest:create` (roles Data Editor, Operations Administrator, Technical
Administrator) can change any section of any DA, from the staff portal's Edit
Details or through the API, and the change is applied without any approval.**
So:

- give those roles on `da-registry-staff-portal` to the DA Services
  Administrators only (they send the approved change);
- DAs and Supervisors get a role that can read but not create a change request
  (for example Data Supervisor: `register:view`, `changeRequest:view`);
- the register history shows who created each change.

To make the registry approve changes again, set `skip_if` back to null on the
two stages (in the seed file, or in the AWE admin portal for one environment).

Verified locally (12 Nov 2026) with a staff user's token: a phone, an education
level, a name and a Kebele change were each applied in about 4 seconds with no
approval task; a 12-digit Fayda ID, another DA's Fayda ID, a bad phone number
and an unknown education level were refused and stored nothing; a file import
still stopped at stage 1 with tasks for `admin` and `alex.carter`; an edit made
in the staff portal as `admin` was applied at once.

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

- **A Development Agent does not sign in to the registry.** DA Services
  serves a DA their own profile through its service account (section 5). The
  `DA Services - Development Agent` group is for staff who act as a DA in the
  registry portal, not for the DAs themselves; a DA user with only Data
  Editor would see every DA.
- **Login:** these roles work with a staff Keycloak token. How DA Services
  users sign in (OAN auth service or Keycloak) is still open.
- **Approver routing:** who approves a Woreda's submissions is the approval
  workflow's job, not the data policies'.
- A Woreda code is unique, but Woreda names are not (23 names repeat). Always
  scope by code.

## 5. A Development Agent's own profile (self-service through DA Services)

Requirement (Shikha, 7 Oct 2026): a DA may update their own profile; the change
is approved in the registry by the same approval as any other. Architecture
(Faiz, 7 Oct 2026): DA Services wraps the registry's staff API, it does not
copy the data.

A DA signs in to **DA Services only**, never to the registry. DA Services
knows which DA the signed-in user is (its own user ↔ DA-ID mapping) and calls
the registry **server to server with its service account**:

| Step | Staff API call | Note |
|---|---|---|
| Find the DA | `POST /register-data/search_in_a_register` with `search_text` = the DA-ID | keep only the item whose `functional_record_id` equals the DA-ID (`search_text` is partial) |
| Show the profile | `POST /register-data/get_tab_records` (`da_details_tab`) | |
| Request a change | `POST /change-requests/create_change_request` on that record | DA Services allows only the contact (`da_contact_section_04`), service (`da_service_section_02`) and location (`da_location_section_03`) sections, and in the service section only `joined_date` and `specialisation`: **not `position` or `reports_to`** (section 6); never identity (name, Fayda ID) |
| Show the status | `POST /change-requests/get_change_request` | `PENDING` in the create response, `APPROVED` a few seconds later (no registry approval, section 2); read `approval_status`, not `awe_request_status_summary` |

- **Service account:** a confidential Keycloak client in realm `staff` with
  service accounts on (local: `da-services-backend`, secret
  `dev-da-services-secret`, created by `keycloak-init.sh`); its service-account
  user gets the client roles `Intake Officer` (form layout, register a DA,
  start a file import), `Data Editor` (view the register, create and view
  change requests) and `Integration Manager` (read what came in, for the status
  of its pushes and the exceptions list) on `da-registry-staff-portal`; it
  cannot approve. Token: `POST /realms/staff/protocol/openid-connect/token`
  with `grant_type=client_credentials`. In other environments DevOps creates
  the client with the same three roles.
- **Who may see or change which record is DA Services' rule**, not the
  registry's: the registry trusts the service account, so DA Services must
  never pass a DA-ID the signed-in user does not own. The registry records the
  change request as created by the service (`created_by`), so DA Services keeps
  its own log of which DA asked.
- **Approval** of a change is DA Services' job (Supervisor, then
  Administrator); the registry applies the change request without an approval
  of its own (section 2, "Changes to a DA").

Verified locally (29 Oct 2026, `da_services_selfservice_probe.py`): the
service-account token found one DA by DA-ID, read its details tab, created a
phone change request; admin approved stage 1 and stage 2; the register showed
the new phone number.

Earlier design, removed on 29 Oct 2026: the DA signed in to the registry with a
Keycloak attribute `da_id` and the registry limited that token to one record
through an override of the platform's data-policy middleware. It needed a
platform override and a Keycloak scope per realm; enforcing it in DA Services
needs neither.

## 6. Positions: who may give one, and who may change it

> **Switched off for now (18 Nov 2026).** For the team demo on dev the rules
> below are not in the metadata: anyone who can fill in the form may give any
> position, a file import and a DA Services push may bring any position, and
> a Data Editor may change `position` and `reports_to`. The code stays and is
> tested; `85_position_and_reporting.sql` says which keys switch it back on.
> Until then, an approver is the only check on a record's position.

The register holds everyone: development agents and the people they report to
(supervisors, officers, the administrator). A person's position decides the
rights of the Keycloak account the registry makes for them
(`docs/keycloak-users.md`), so it is not a free choice of whoever fills in the
form. The rules are metadata on the Position and "Reports to" widgets
(`85_position_and_reporting.sql`); the code is
`register_domain/services/position_rights.py`.

| Who | Positions they may give |
|---|---|
| A user with the registry role **Operations Administrator** | every position |
| Anyone else who may fill in the form (a supervisor: Intake Officer) | Development Agent and Senior DA only |
| A file import or a DA Services push | Development Agent and Senior DA only |

| Who | May change `position` or `reports_to` of a registered record |
|---|---|
| Intake Officer, Data Supervisor or Operations Administrator | yes (a position above Senior DA still needs Operations Administrator) |
| A user with Data Editor only (a development agent) | no |

What the API answers:

- `Position: only an administrator can give this position (ADMIN). Choose another position, or ask an administrator to register this person.`
- `Position: you cannot change this. Ask your supervisor to change it.` (also for `Reports to (ID)`)
- `Position: ADMIN cannot be given in a file import or by DA Services. An administrator registers this person in the registry.`

A field sent with the value the register already has is not a change: the form
sends a whole section, so a supervisor can still correct another field of an
administrator's record.

On the form, a user without the right does not see the other positions in the
dropdown (the form reads a permission for this, `incomingMessage:view`, which
Operations Administrator has and the supervisor roles do not; the staff UI
knows a user's permissions, not their roles). The API decides by the role.

**DA Services' service account** has Intake Officer, so the registry lets it
change a position between Development Agent and Senior DA and change
`reports_to`. When it acts for a development agent (self-service, section 5)
the registry cannot tell: DA Services must not send `position` or `reports_to`
there. With the user's own token instead of the service account, the registry
refuses them itself.

Not covered: the approval of a new record is the same for every position. An
approver should look at the position of a record whose position is above
Senior DA; a stricter approval for those records is a change of the approval
policy, not of the registry.

## 7. Starting a new environment

A new environment has no record in the register, and nobody in it can be given
a position above Senior DA except by an administrator. So the first
administrator does not come from the register:

1. **Keycloak is set up**: the `staff` realm, the DA Services groups
   (section 1), and one user in `DA Services - OAN Administrator`. On the local
   stack `docker/local-dev/keycloak-init.sh` does this; elsewhere it is part
   of the installation.
2. **Two approvers** exist and are named in the two DA approval policies.
3. **Master Data** has the DA lists, among them `DA_POSITION` with every
   position (openg2p-data).
4. **That administrator signs in to the registry** and registers people from
   the top down: administrators first (they report to no one), then officers
   and supervisors, then development agents. "Reports to" must name a person
   already in the register, so a file import follows the same order, and a
   file can bring development agents only.
5. An administrator who already has a Keycloak login is registered with the
   **same email** as that login, so the registry links the record to it
   instead of making a second account (`docs/keycloak-users.md`).

The first administrator's login is made outside the register and is the most
powerful one. Give it to few people, and change its password on the first day.
