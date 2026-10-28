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

### Who approves a DA

Every submitted DA and every change request goes through the platform's
default two-level approval: Stage 1 Officers, then Stage 2 Officers. The
repository seeds only the platform's example approvers for a fresh local
stack (`awe_meta_data/`): Stage 1 = `alex.carter`, Stage 2 = `nina.patel`,
both created by `docker/local-dev/keycloak-init.sh`.

Who approves in a real environment is configuration, not code (decision of
27-28 Oct 2026, Faiz / Asmit): after deployment an administrator edits the
two DA policies in the AWE admin portal and replaces the example users, for
instance with a `role` rule (a Keycloak client role such as Operations
Administrator or Intake Validator on `da-registry-staff-portal`; AWE's service
account needs `view-users` and `view-clients`) or with named users. Routing a
Woreda's submissions to its own supervisor (DA-33) is the same kind of
configuration once the approver roles exist per Woreda.

Bulk import and the DA Services push are approved automatically today
(`DA_AUTO_APPROVE_IMPORTS=true`); the decision of 23 Oct 2026 is that they
must be approved manually too, which is pending in this branch.

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

- **A Development Agent can read every DA, not only their own.** The registry
  has no "own record" rule. The DA app must use the DA's own ID; otherwise the
  DA can be given a narrow (for example Kebele-level) policy.
- **Login:** these roles work with a staff Keycloak token. How DA Services
  users sign in (OAN auth service or Keycloak) is still open (DA-167).
- **Approver routing:** who approves a Woreda's submissions is the approval
  workflow's job (DA-33), not the data policies'.
- A Woreda code is unique, but Woreda names are not (23 names repeat). Always
  scope by code.
