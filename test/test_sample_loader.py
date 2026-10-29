"""The db-seed sample loader enters each sample DA through the intake API and approves it at stage 1 as
alex.carter, then stage 2 as nina.patel, signing them in like the staff portal."""

import importlib.util
from pathlib import Path

import pytest

SEED = Path(__file__).resolve().parents[1] / "docker/db-seed"


@pytest.fixture(scope="module")
def loader():
    spec = importlib.util.spec_from_file_location("da_sample_loader", SEED / "load_sample_data.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_approvers_sign_in_like_the_portal_and_keycloak_is_never_changed():
    code = (SEED / "load_sample_data.py").read_text(encoding="utf-8")
    # The only token grant is the intake service account's client credentials.
    assert code.count('"grant_type"') == 1 and '"grant_type": "client_credentials"' in code
    for forbidden in ("KEYCLOAK_ADMIN", "admin-cli", "/admin/realms", "directAccessGrants", '"grant_type": "password"',
                      "/approve_change_request", "INSERT INTO g2p_register"):
        assert forbidden not in code, forbidden
    for required in ("/auth/start_authentication_transaction", "kc-form-login", "/auth/callback",
                     "/awe/claim_task", "/awe/submit_task_decision", "INTAKE_SEED_APPROVER_1",
                     "INTAKE_SEED_APPROVER_2", "INTAKE_SEED_PASSWORD", "STAFF_IAM_URL"):
        assert required in code, required


class FakeApprover:
    def __init__(self, name, stage, open_tasks, calls):
        self.username, self.stage, self.open_tasks, self.calls = name, stage, open_tasks, calls

    def post(self, path, payload):
        self.calls.append((self.username, path, payload))
        if path == "/awe/list_my_tasks":
            return {"data": {"items": [t for t in self.open_tasks if t["stage_order"] == self.stage]}}
        if path == "/awe/submit_task_decision":
            self.open_tasks[:] = [t for t in self.open_tasks if t["id"] != payload["task_id"]]
            if self.stage == 1:
                self.open_tasks.append({"id": "t2", "artifact_id": payload["artifact_id"], "stage_order": 2})
        return {}


def test_each_submission_is_approved_at_stage_1_then_stage_2(loader):
    calls, tasks = [], [{"id": "t1", "artifact_id": "sub-1", "stage_order": 1},
                        {"id": "other", "artifact_id": "sub-9", "stage_order": 1}]
    approvers = [FakeApprover("alex.carter", 1, tasks, calls), FakeApprover("nina.patel", 2, tasks, calls)]
    loader.approve(approvers, "sub-1", 5)
    decisions = [(user, p["task_id"], p["current_stage"], p["action"]) for user, path, p in calls
                 if path == "/awe/submit_task_decision"]
    assert decisions == [("alex.carter", "t1", 1, "approve"), ("nina.patel", "t2", 2, "approve")]
    assert [t["id"] for t in tasks] == ["other"]  # another intake's task is left alone


def test_a_stage_task_that_never_opens_fails(loader):
    approvers = [FakeApprover("alex.carter", 1, [], []), FakeApprover("nina.patel", 2, [], [])]
    loader.time.sleep = lambda seconds: None
    with pytest.raises(RuntimeError, match="no stage 1 task for alex.carter"):
        loader.approve(approvers, "sub-1", 0)
