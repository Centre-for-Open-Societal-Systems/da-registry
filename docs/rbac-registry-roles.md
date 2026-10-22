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

Decision (22 Oct 2026): DAs from the bulk import and from the DA Services
push are approved automatically (`DA_AUTO_APPROVE_IMPORTS=true`); a DA entered
on the web intake form is approved by an administrator.

A submitted DA (web form) goes to AWE, which assigns the approval task by the
seeded approver rules (`awe_meta_data/30_approver_rule.sql`). The rules are by
role on the client `da-registry-staff-portal`, so they work in every
environment without naming a user:

| Stage | Approvers: users holding either role |
|---|---|
| DA intake form | Operations Administrator, Intake Validator |
| DA change request | Operations Administrator, Data Validator |

AWE asks Keycloak for the users that hold the role **directly**. A role that
comes through a group (the DA Services role groups above) is not seen by that
lookup. So an approver must hold the role directly, or, once the DA Services
groups exist in an environment, a `group` rule can be added for
`DA Services - Supervisor` and `DA Services - OAN Administrator` (a group rule
fails the whole resolution while the group is missing). AWE's resolver client
needs `view-users` and `view-clients` in Keycloak. Routing a submission to its
own Woreda's supervisor is DA-33.

## 2. Scope by Woreda, Zone or Region (DA-166)

DA records carry `woreda_code`, `zone_code` and `region_code` (Master Data
P-codes, DA-225). A data policy filters on one of these. For example, the
policy `DP_DA_WOREDA_ET010101` uses this filter:

```json
{"type":"GROUP","operator":"AND","children":[
  {"type":"CONDITION","field_id":"woreda_code","operator":"eq","value":"ET010101"}]}
```

The policy has `policy_target` REGISTER_RECORD and `policy_type` ALLOW, and
belongs to the application `da-registry-staff-portal`.

A user who holds the policy's role sees only matching DAs. This applies to DA
search, DA details, intake submissions and change requests. Opening a DA
outside the scope returns `REG-ERR-012`. A user with no data policy sees every
DA, so Development Agent and OAN Administrator are not scoped.

**Local stack:**

```bash
scripts/da-scope-local.sh woreda ET010101 <username>   # Supervisor
scripts/da-scope-local.sh region ET04 <username>       # Executive
```

The script does three things:

1. Adds the policy row to the IAM database.
2. Creates the Keycloak role.
3. Gives the role to the user.

The user must sign in again to get a new token.

**Deployment:** an IAM administrator (`dataPolicy:create`) adds the policy
through the IAM admin API or UI. That also creates the Keycloak role. After
that, the role is given to each user, or to a per-Woreda group.

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
