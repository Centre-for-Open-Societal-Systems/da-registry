# Keycloak accounts for the people in the DA register

Everyone in the DA register (development agents, supervisors, officers, the
administrator) signs in to DA Services with a Keycloak account. The registry
creates that account when a record is approved, so nobody is onboarded twice.
The code is `da-extension/src/openg2p_registry_da_extension/keycloak_users.py`;
it runs in the celery worker.

It is **off by default**. Nothing changes in Keycloak until
`DA_KEYCLOAK_USERS_ENABLED` is `true`.

## What the registry creates

| Keycloak field | Value |
|---|---|
| Username | The DA-ID, for example `DA-4071727521`. Keycloak stores usernames in lower case; sign-in is not case sensitive. |
| First name | The record's name |
| Last name | Father's name and grandfather's name |
| Email | The record's email |
| Attribute `da_record_id` | The record's `internal_record_id`: the id the staff API opens and changes a record by (`get_subject_record`, change requests) |
| Roles | By position, from `DA_KEYCLOAK_ROLES` |
| Password | `DA_KEYCLOAK_INITIAL_PASSWORD`, marked temporary: Keycloak asks for a new one at the first sign-in. On a test environment `DA_KEYCLOAK_FORCE_PASSWORD_CHANGE=false` lets it stay. Without a first password the account has none. |

A username or an email Keycloak already has is not created again: the
attribute and the roles are put on that account, and its password is left
alone. An account that already carries another record's id is not touched:
the record fails with the reason, because two people in the register share an
email. The registry does not refuse a shared email when a record is saved, so
such records are found here.

## When it runs

- Right after the platform's worker gives an approved record its DA-ID.
- Every `DA_KEYCLOAK_RETRY_SECONDS` (default 600) for records that failed.
- In batches of `DA_KEYCLOAK_BATCH` (default 25), oldest record first, one run
  at a time across workers. Switching it on in an environment that already has
  records creates their accounts batch by batch.

An approval never waits for Keycloak and never fails because of it.

## What an administrator sets up once

1. **Rights of the service account.** The worker signs in to Keycloak as the
   client it already uses for Master Data (`da-registry-backend`; another one
   can be named with `DA_KEYCLOAK_CLIENT_ID` and `DA_KEYCLOAK_CLIENT_SECRET`).
   Give its service account these roles of the client `realm-management`, in
   the realm the users are in: `manage-users`, `view-users`, `query-users`,
   and `view-clients` (needed to give client roles).
2. **The attribute.** Add `da_record_id` to the realm's user profile
   (Realm settings → User profile), with view and edit permission for
   **admin only**. A user who could edit it could point their account at
   another person's record. Another name can be set with
   `DA_KEYCLOAK_RECORD_ATTRIBUTE`; DA Services must read the same name.
3. **The token.** For DA Services to find the attribute in the token, its
   Keycloak client needs a "User attribute" mapper for `da_record_id`. This is
   set on DA Services' client, not by the registry.
4. **Settings of the celery worker** (Helm: `registry.celeryWorker.envVars`):

| Setting | Meaning |
|---|---|
| `DA_KEYCLOAK_USERS_ENABLED` | `true` to switch it on |
| `DA_KEYCLOAK_ROLES` | JSON, position code → roles; `*` is every position. A role is `client-id:Role name` or a realm role: `{"*": ["da-services:User"], "SUPERVISOR": ["da-services:Supervisor"]}` |
| `DA_KEYCLOAK_INITIAL_PASSWORD` | The first password. Keep it in a secret, not in the values file. |
| `DA_KEYCLOAK_FORCE_PASSWORD_CHANGE` | Default: the first password must be changed at the first sign-in. `false` lets it stay; for a test environment only. |
| `DA_KEYCLOAK_ADMIN_URL` | `https://<keycloak>/admin/realms/<realm>`; by default taken from the token URL the worker already has |
| `DA_KEYCLOAK_TOKEN_URL`, `DA_KEYCLOAK_CLIENT_ID`, `DA_KEYCLOAK_CLIENT_SECRET` | Only when the account is not the Master Data client |
| `DA_KEYCLOAK_RECORD_ATTRIBUTE` | Default `da_record_id` |
| `DA_KEYCLOAK_BATCH`, `DA_KEYCLOAK_MAX_ATTEMPTS`, `DA_KEYCLOAK_RETRY_SECONDS` | Defaults 25, 10, 600 |

The first password is a deployment's decision. One password for everyone is
acceptable on a test environment only: the username is the DA-ID, which staff
can see, so whoever knows a DA-ID could sign in before the person does.

## Seeing what happened

The table `da_keycloak_users` in the registry database has one row per record:

| Column | Meaning |
|---|---|
| `status` | `CREATED` (a new account), `LINKED` (an account Keycloak already had), `FAILED` |
| `keycloak_user_id` | The account's id in Keycloak |
| `attempts`, `last_error`, `updated_at` | For a failure: how often it was tried, why, and when |

A record that failed `DA_KEYCLOAK_MAX_ATTEMPTS` times is not tried again; to
retry it, delete its row. Common reasons:

| `last_error` | What to do |
|---|---|
| `Keycloak did not keep the attribute 'da_record_id': add it to the realm's user profile` | Step 2 above |
| `Keycloak has no role ...` / `Keycloak has no client ...` | Correct `DA_KEYCLOAK_ROLES`, or create the role |
| `the Keycloak account '...' already belongs to another record (...): two people cannot share an email` | Correct the email of one of the two records, then delete the failed row |
| `Keycloak refused the user (400): ...` | The record's name or email does not pass the realm's user profile rules |

When Keycloak cannot be reached, or the service account lacks a right, no row
is written and no attempt is counted: the worker log says
`Keycloak users: stopped, ...` and the next run tries again.

## Not covered

- A later change of name, email or position in the register is not carried to
  the account.
- An account is not disabled when its record stops being active.
- Accounts are not removed.

## Local stack

`docker/local-dev/keycloak-init.sh` gives `da-registry-backend` the rights and
adds the attribute; `docker-compose.yml` switches the worker's setting on with
a first password for local use.
