"""Temporary in-process workarounds for platform gaps (temporary_platform_overrides.py).

Each test skips when the platform package it targets is not installed in the
process running the tests (the worker fix needs the celery image); the staff-API image covers the IAM one.
"""

import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest

# The platform's partner-API and worker packages import the extension through
# the alias that their container entrypoint creates; create it here too.
sys.modules.setdefault("openg2p_registry_extensions", importlib.import_module("openg2p_registry_da_extension"))

from openg2p_registry_da_extension.register_domain import temporary_platform_overrides as po


def test_permissions_for_application_keeps_only_this_client():
    payload = [
        {"application_mnemonic": "farmer-registry-staff-portal", "permissions": ["register:view", "register:export"]},
        {"application_mnemonic": "da-registry-staff-portal", "permissions": ["register:view", "changeRequest:create"]},
        None,
    ]
    assert po.permissions_for_application(payload, "da-registry-staff-portal") == {"register:view", "changeRequest:create"}
    assert po.permissions_for_application(payload, "unknown") == set()
    assert po.permissions_for_application(None, "x") == set()


def test_permission_lookup_is_scoped_to_this_application(monkeypatch):
    pytest.importorskip("iam_core")
    import httpx
    from iam_core.user_auth.middleware.resolve_permissions import ResolvePermissionMiddleware

    assert po.install_scoped_permission_lookup() is True
    assert po.install_scoped_permission_lookup() is True  # idempotent
    calls = {}

    class FakeResponse:
        def raise_for_status(self): pass
        def json(self):
            return [{"application_mnemonic": "other-portal", "permissions": ["a:b"]},
                    {"application_mnemonic": "da-registry-staff-portal", "permissions": ["register:view"]}]

    class FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url, params=None, headers=None):
            calls.update(url=url, params=params, headers=headers); return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)
    middleware = ResolvePermissionMiddleware(app=None, client_id="da-registry-staff-portal")
    middleware._config = SimpleNamespace(auth_provider_api_url="http://iam:8000")
    request = SimpleNamespace(state=SimpleNamespace(auth=SimpleNamespace(credentials="tok-123")))
    token = po._current_request.set(request)
    try:
        permissions = asyncio.run(middleware._fetch_permissions_for_roles(["Data Editor"]))
    finally:
        po._current_request.reset(token)
    assert permissions == {"register:view"}
    assert calls["url"].endswith("/user-access/get_application_permissions_for_user")
    assert calls["params"] == {"application_mnemonic": "da-registry-staff-portal"}
    assert calls["headers"] == {"Authorization": "Bearer tok-123"}




def _history_probe():
    pytest.importorskip("openg2p_registry_core")
    from openg2p_registry_core.models import G2PRegisterHistory

    name = "G2PRegisterHistoryHistorySourceProbe"
    probe = getattr(sys.modules[__name__], "_PROBE", None)
    if probe is None:
        probe = type(name, (G2PRegisterHistory,), {"__tablename__": "g2p_register_history_history_source_probe"})
        globals()["_PROBE"] = probe
    return probe


def _load_history(source):
    from datetime import datetime

    from sqlalchemy import create_engine, insert, select
    from sqlalchemy.orm import Session

    probe = _history_probe()
    assert po.install_history_change_request_source()
    engine = create_engine("sqlite://")
    table = probe.__table__
    table.create(engine)
    samples = {str: "x", bool: False, int: 1, datetime: datetime(2026, 10, 29)}
    row = {column.name: samples.get(column.type.python_type, "x") for column in table.columns}
    row["change_request_source"] = source
    with Session(engine) as session:
        session.execute(insert(table).values(**row))
        return session.scalars(select(probe)).one()


def test_history_source_has_the_value_the_platform_reads():
    from sqlalchemy import inspect

    record = _load_history("INTAKE_FORM")
    assert record.change_request_source.value == "INTAKE_FORM"
    assert record.change_request_source == "INTAKE_FORM"
    assert not inspect(record).modified


def test_unknown_history_source_is_left_as_stored():
    assert _load_history("SOMETHING_ELSE").change_request_source == "SOMETHING_ELSE"


def test_history_source_install_is_idempotent():
    pytest.importorskip("openg2p_registry_core")
    from openg2p_registry_core.models import G2PRegisterHistory
    from sqlalchemy import event

    assert po.install_history_change_request_source()
    assert po.install_history_change_request_source()
    assert event.contains(G2PRegisterHistory, "load", po._history_loaded)


def test_history_row_without_change_request_is_returned():
    pytest.importorskip("openg2p_registry_core")
    from openg2p_registry_core.schemas.register_payload import RecordHistoryData, RecordHistoryListData
    from openg2p_registry_core.schemas.register_response import RecordHistoryDataResponseBody

    assert po.install_history_without_change_request()
    assert po.install_history_without_change_request()
    row = RecordHistoryData(history_record_id="h1", internal_record_id="r1", tab_id="t", section_id="s",
                            change_request_id=None, submission_id="sub-1")
    listing = RecordHistoryListData(register_id="reg", internal_record_id="r1", tab_id="t", history_records=[row])
    record = RecordHistoryDataResponseBody(response_payload=listing).model_dump()["response_payload"]["history_records"][0]
    assert record["change_request_id"] is None and record["submission_id"] == "sub-1"
    assert RecordHistoryData(history_record_id="h", internal_record_id="r", tab_id="t", section_id="s",
                             change_request_id="cr-1").change_request_id == "cr-1"
