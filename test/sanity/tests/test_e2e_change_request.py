"""Change request -> AWE approval -> applied change -> version history -> audit.

The flow under test:
  1. raise a change request on the sanity DA via staff-portal-api;
  2. AWE starts a workflow from the register's bound approval policy;
  3. approve each stage through the **AWE proxy**;
  4. AWE posts an HMAC-signed decision webhook back to the registry;
  5. the registry applies the change and writes a history row;
  6. Audit Manager records the events.

Identity: the suite's OWN seeded user (sanity.keycloak_seed), logged in with the
password grant. The shipped demo users cannot be reused — keycloak-init gives
them a temporary password, so Keycloak forces UPDATE_PASSWORD and their password
grant fails. sanity.awe_seed therefore names the sanity user as an approver on
each stage of the shipped policy, additively, leaving the demo-user rules alone.
`forbid_self_approval` is FALSE on the shipped policy, so the one user both
raises the CR and clears every stage.

It never calls `/change-requests/approve_change_request`: that endpoint flips
the CR to approved **without inspecting the AWE workflow at all**, so approving
through it would make this test pass while proving nothing about the approval
policy. The only meaningful path is the AWE proxy.

AWE does not apply the decision itself — it POSTs an HMAC-signed webhook to the
registry, which applies the change and writes history. So the change lands
asynchronously and the assertions below poll rather than read once.

DA field-specific test (Set 2): the register/history rows the change is
verified against live in the DA register tables (g2p_register_das /
g2p_register_history_das). The register id, CR tab and section are supplied
as env by the Helm chart (sanity.* values).
"""

import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from sanity import audit, db, fixtures


def _field_value(cfg):
    rows = db.query(
        cfg.registry_dsn,
        f'SELECT "{fixtures.CR_FIELD}" AS v FROM "public"."g2p_register_das" '
        f'WHERE "internal_record_id" = %s',
        (fixtures.FARMER_INTERNAL_ID,),
    )
    assert rows, f"sanity DA {fixtures.FARMER_INTERNAL_ID} not found"
    return rows[0]["v"]


def _wait_until(predicate, timeout, interval=3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


@pytest.fixture(scope="module")
def change_request(cfg, staff_client, farmer_seeded, awe_approver):
    """Raise a CR that changes CR_FIELD, and return its id."""
    from sanity.steplog import note
    note(f"staff-portal-api login OK as '{cfg.staff_username}'; sanity approver registered on the AWE stages")
    note(f"raising change request: set {fixtures.CR_FIELD}={fixtures.CR_VALUE_UPDATED!r} on record "
         f"{fixtures.FARMER_INTERNAL_ID} (register={cfg.reg_type}, tab={cfg.cr_tab_id}, section={cfg.cr_section_id})")
    payload = {
        "register_id": cfg.farmer_register_id,
        "tab_id": cfg.cr_tab_id,
        "section_id": cfg.cr_section_id,
        "section_register_id": cfg.farmer_register_id,
        "internal_record_id": fixtures.FARMER_INTERNAL_ID,
        "change_payload": [
            {
                "internal_record_id": fixtures.FARMER_INTERNAL_ID,
                "edit_action": "UPDATE",
                fixtures.CR_FIELD: fixtures.CR_VALUE_UPDATED,
            }
        ],
    }
    # Just after a fresh install the registry's permission resolution can lag
    # staff-portal-api readiness: a valid token briefly resolves to no
    # permissions, so create_change_request returns 403. Retry with a fresh
    # token until authorization is ready (or the timeout elapses). Once the
    # create succeeds the same staff_client token is good for the later
    # permission-gated calls (e.g. get_number_of_versions).
    deadline = time.time() + cfg.auth_ready_timeout
    while True:
        try:
            resp = staff_client.create_change_request(payload)
            break
        except AssertionError as exc:
            if "-> 403" in str(exc) and time.time() < deadline:
                time.sleep(5)
                staff_client.relogin()
                continue
            raise
    body = (resp.get("response_body") or {}).get("response_payload") or resp
    cr_id = body.get("change_request_id") or body.get("id")
    assert cr_id, f"could not find change_request_id in response: {resp}"
    note(f"change request created id={cr_id} — status pending, awaiting AWE approval")
    return cr_id


@pytest.mark.e2e
def test_change_request_is_created_pending(cfg, change_request):
    """Every register write is a change request — nothing is applied yet."""
    assert _field_value(cfg) == fixtures.CR_VALUE_INITIAL, (
        "the register row changed before the change request was approved — "
        "the change should only be applied on approval"
    )


_OPEN_TASKS = """
SELECT t.id AS task_id, t.stage_order, t.assignee
  FROM "public"."approval_task" t
  JOIN "public"."approval_request" r ON r.id = t.request_id
 WHERE r.artifact_id = %s
   AND t.status IN ('open', 'claimed')
 ORDER BY t.stage_order;
"""


def _open_tasks(cfg, cr_id):
    """Every OPEN task on the change request, across all assignees.

    Read from the AWE DB rather than `list_my_tasks`, because the shipped policy
    stages are mode='all' and include demo approvers (alex.carter / nina.patel)
    besides the sanity user — so we must approve THEIR tasks too. The sanity user
    holds the AWE admin role, so it may decide any of them.
    """
    return db.query(cfg.awe_dsn, _OPEN_TASKS, (str(cr_id),))


@pytest.mark.e2e
def test_approval_through_awe_applies_the_change(cfg, staff_client, change_request, step):
    """Approve every task on the request until the change is applied.

    Tasks are re-read each round rather than assuming a stage count, so a one-
    or three-level policy needs no change here. A later stage only becomes
    visible once the earlier one is cleared, so each round waits briefly for AWE
    to advance the workflow. The sanity user holds AWE_ADMIN, so it approves
    every task regardless of assignee — the shipped mode='all' stages require
    the demo approvers' tasks to be decided too.
    """
    approved_any = False
    for _ in range(cfg.max_approval_rounds):
        if _field_value(cfg) == fixtures.CR_VALUE_UPDATED:
            break
        tasks = _open_tasks(cfg, change_request)
        step(f"AWE round: {len(tasks)} open approval task(s) offered for CR {change_request}")
        if not tasks:
            # Either nothing was ever offered, or the next stage's tasks aren't
            # created yet — wait once for them to appear.
            if approved_any:
                break
            if not _wait_until(lambda: _open_tasks(cfg, change_request), timeout=30):
                break
            continue
        for task in tasks:
            staff_client.submit_task_decision({
                "task_id": task["task_id"],
                "action": "approve",
                "comment": f"approved by sanity e2e (assignee {task['assignee']})",
                "artifact_id": str(change_request),
                "artifact_type": "registry.change_request",
                "current_stage": task["stage_order"] or 1,
            })
            step(f"approved AWE task {task['task_id']} (stage {task['stage_order']}, assignee {task['assignee']})")
            approved_any = True
        step("waiting for AWE to advance the workflow (next stage or apply the change)…")
        # Let AWE advance to the next stage (or apply the change) before re-reading.
        _wait_until(
            lambda: _field_value(cfg) == fixtures.CR_VALUE_UPDATED or _open_tasks(cfg, change_request),
            timeout=30,
        )

    if not approved_any:
        pytest.skip(
            f"no AWE tasks were created for this change request. Either AWE is "
            f"disabled (global.aweEnabled=false — then start_change_request_workflow "
            f"silently no-ops) or no policy is bound to the register."
        )

    # AWE applies the decision by POSTing an HMAC-signed webhook back to the
    # registry, so the change lands asynchronously — poll, do not read once.
    step(f"all stages cleared; waiting up to {cfg.awe_settle_timeout}s for AWE's HMAC-signed decision "
         "webhook to apply the change to the register")
    applied = _wait_until(
        lambda: _field_value(cfg) == fixtures.CR_VALUE_UPDATED,
        timeout=cfg.awe_settle_timeout,
    )
    if applied:
        step(f"change applied — {fixtures.CR_FIELD} is now {fixtures.CR_VALUE_UPDATED!r} in the register ✓")
    assert applied, (
        f"'{fixtures.CR_FIELD}' is still '{_field_value(cfg)}' after clearing every "
        f"offered stage and waiting {cfg.awe_settle_timeout}s — AWE's decision webhook "
        f"may not have reached the registry (check the callback secret / HMAC signature)."
    )


_HISTORY = (
    'SELECT "history_record_id", "change_request_id" '
    'FROM "public"."g2p_register_history_das" '
    'WHERE "internal_record_id" = %s'
)


@pytest.mark.e2e
def test_version_history_retains_the_previous_record(cfg, staff_client, change_request):
    """Approval must write a history row; the previous value survives in the DB.

    Polled, because the webhook that applies the change and writes history lands
    asynchronously — the row can lag the `middle_name` update by a moment.
    """
    rows = []

    def _has_history():
        nonlocal rows
        rows = db.query(cfg.registry_dsn, _HISTORY, (fixtures.FARMER_INTERNAL_ID,))
        return bool(rows)

    assert _wait_until(_has_history, timeout=cfg.awe_settle_timeout), (
        "no history row for the sanity DA after approval — history is written by "
        "insert_into_register_history during approve, so its absence means the change "
        "was never applied through the approval path"
    )

    versions = staff_client.get_number_of_versions({
        "register_id": cfg.farmer_register_id,
        "internal_record_id": fixtures.FARMER_INTERNAL_ID,
        "tab_id": cfg.cr_tab_id,
    })
    body = (versions.get("response_body") or {}).get("response_payload") or versions
    count = body.get("number_of_versions") or body.get("count") or len(rows)
    assert count >= 1, f"expected at least one prior version, got {count}"


@pytest.mark.e2e
def test_audit_events_are_recorded(cfg, staff_client, change_request):
    """The change-request flow must leave an audit trail in Audit Manager.

    Audit Manager has no query API, so this reads its `audit_events` table. The
    write is fire-and-forget -> Kafka -> Postgres, so it polls. The staff-portal-api
    audit middleware keys events by the caller's `actor_id` (the user's sub) and
    does not populate `resource_id`, so the trail for this flow is found by the
    sanity user's subject — the create + approve calls all generate events.
    """
    if not cfg.audit_dsn:
        pytest.skip("audit DB not configured — cannot assert the audit trail")

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    rows = audit.wait_for(cfg, staff_client.subject, since)
    assert rows, (
        f"no audit events for the sanity user ({staff_client.subject}) within "
        f"{cfg.audit_timeout}s. Audit is emitted fire-and-forget by the API "
        f"middleware; check that auditEnabled=true and the Audit Manager URL is reachable."
    )
