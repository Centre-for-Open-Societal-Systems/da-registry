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


KEYCLOAK_TOKEN = "https://keycloak.development.oanstaging.com/realms/staff/protocol/openid-connect/token"


@pytest.mark.parametrize("name, label, environ, expected", [
    ("STAFF_IAM_URL", "staff-iam", {"STAFF_TOKEN_URL": KEYCLOAK_TOKEN}, "https://staff-iam.development.oanstaging.com"),
    ("MDS_API_URL", "master-data", {"STAFF_TOKEN_URL": KEYCLOAK_TOKEN},
     "https://master-data.development.oanstaging.com"),
    ("MDS_API_URL", "master-data", {"MDS_API_URL": "http://mds.internal/", "STAFF_TOKEN_URL": KEYCLOAK_TOKEN},
     "http://mds.internal"),
    ("STAFF_IAM_URL", "staff-iam",
     {"STAFF_TOKEN_URL": "https://auth.example.org/realms/staff/protocol/openid-connect/token"}, ""),
    ("STAFF_IAM_URL", "staff-iam", {}, ""),
])
def test_iam_and_master_data_are_the_hosts_beside_keycloak(loader, monkeypatch, name, label, environ, expected):
    for var in ("STAFF_IAM_URL", "MDS_API_URL", "STAFF_TOKEN_URL"):
        monkeypatch.delenv(var, raising=False)
    for var, value in environ.items():
        monkeypatch.setenv(var, value)
    assert loader.beside_keycloak(name, label) == expected


def test_image_pins_an_openg2p_data_with_the_sample_das():
    text = (SEED / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG OPENG2P_DATA_REF=34b239463cc38af8c028428df1eb52d786cc14c2" in text


class FlakyOpener:
    """Answers with the given outcomes in turn: an exception to raise, or a status code."""

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    def open(self, request, timeout):
        import contextlib
        import io
        import urllib.error

        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome >= 400:
            raise urllib.error.HTTPError(request.full_url, outcome, "x", {}, io.BytesIO(b"{}"))
        response = io.BytesIO(b"{}")
        response.status, response.headers = outcome, {}
        return contextlib.nullcontext(response)


def test_network_errors_and_gateway_statuses_are_retried(loader, monkeypatch):
    import urllib.error
    import urllib.request

    monkeypatch.setattr(loader.time, "sleep", lambda seconds: None)
    request = urllib.request.Request("https://master-data.example.org/geo/get_all_geo_levels")
    opener = FlakyOpener(urllib.error.URLError("connection reset"), TimeoutError("timed out"), 502, 200)
    assert loader.fetch(opener, request)[0] == 200 and opener.calls == 4
    assert loader.fetch(FlakyOpener(401), request)[0] == 401
    with pytest.raises(RuntimeError, match="unreachable"):
        loader.fetch(FlakyOpener(*[OSError("unreachable")] * loader.NETWORK_ATTEMPTS), request)


def test_tls_checks_follow_the_chart_setting(loader, monkeypatch):
    import ssl

    monkeypatch.setenv("INTAKE_SEED_VERIFY_TLS", "false")
    assert loader.tls_context().verify_mode == ssl.CERT_NONE
    monkeypatch.delenv("INTAKE_SEED_VERIFY_TLS")
    assert loader.tls_context().verify_mode == ssl.CERT_REQUIRED


GEO = {"ET01010102": {"level_value_id": "ET01010102", "level_id": "l4", "level_mnemonic": "kebele",
                      "level_value_mnemonic": "Kebele 02", "parent_level_value_id": None}}
DA = {"da_id": "DA-1", "fayda_fan": "9311502628318720", "geo_pcode": "ET01010102"}


@pytest.mark.parametrize("earlier, submits, outcome", [
    ([], [None], "approved"),
    ([("sub-wait", "FINAL", "PENDING", "rec-1")], [], "approved"),
    ([("sub-draft", "DRAFT", None, "rec-2")], [("sub-draft", "rec-2")], "approved"),
])
def test_a_rerun_approves_waiting_submissions_and_completes_drafts(loader, monkeypatch, earlier, submits, outcome):
    sent, approved = [], []
    monkeypatch.setattr(loader, "earlier_submissions", lambda fayda: earlier)
    monkeypatch.setattr(loader, "submit", lambda client, fields, geo, draft=None: sent.append(draft) or
                        ("submitted", (draft or ("sub-new",))[0]))
    monkeypatch.setattr(loader, "approve", lambda approvers, sid, timeout: approved.append(sid))
    assert loader.load_one(None, [], 5, GEO, {}, DA, {}) == outcome
    assert sent == submits and len(approved) == 1


@pytest.mark.parametrize("message, outcome", [
    ("Fayda ID 9311502628318720 is already registered as DA-3700000001. Open that record instead.", "skipped"),
    ("Fayda ID 9311502628318720 is already in submission APP-1, which is waiting for a decision.", "skipped"),
    ("Something already went wrong", "failed"),
])
def test_only_the_uniqueness_wording_counts_as_already_there(loader, monkeypatch, message, outcome):
    monkeypatch.setattr(loader, "earlier_submissions", lambda fayda: [])
    client = type("C", (), {"staff": "s", "call": lambda self, base, path, payload: (False, message, None)})()
    assert loader.load_one(client, [], 5, GEO, {}, DA, {}) == outcome


def test_a_missing_kebele_skips_that_da_only(loader):
    assert loader.load_one(None, [], 5, {}, {}, DA, {}) == "failed"


def test_sample_data_never_fails_the_upgrade(loader, monkeypatch, tmp_path):
    pack = tmp_path / "packs" / "ETH-OAN" / "samples"
    pack.mkdir(parents=True)
    (pack / "development_agents.json").write_text("[]", encoding="utf-8")
    for name in ("STAFF_API_URL", "STAFF_TOKEN_URL", "STAFF_CLIENT_ID", "INTAKE_SEED_PASSWORD", "STAFF_IAM_URL",
                 "MDS_API_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENG2P_DATA_DIR", str(tmp_path))
    assert loader.main() == 0
