"""In-process fixes for three platform bugs (platform_overrides.py).

Each test skips when the platform package it targets is not installed in the
process running the tests (the partner-API fix needs the partner-API image,
the worker fix the celery image); the staff-API image covers the IAM one.
"""

import asyncio
import datetime
import importlib
import sys
from types import SimpleNamespace

import pytest

# The platform's partner-API and worker packages import the extension through
# the alias that their container entrypoint creates; create it here too.
sys.modules.setdefault("openg2p_registry_extensions", importlib.import_module("openg2p_registry_da_extension"))

from openg2p_registry_da_extension import platform_overrides as po


def test_permissions_for_application_keeps_only_this_client():
    payload = [
        {"application_mnemonic": "farmer-registry-staff-portal", "permissions": ["register:view", "register:export"]},
        {"application_mnemonic": "da-registry-staff-portal", "permissions": ["register:view", "changeRequest:create"]},
        None,
    ]
    assert po.permissions_for_application(payload, "da-registry-staff-portal") == {"register:view", "changeRequest:create"}
    assert po.permissions_for_application(payload, "unknown") == set()
    assert po.permissions_for_application(None, "x") == set()


def test_partner_responses_serialise_datetimes():
    pytest.importorskip("openg2p_registry_partner_api")
    from openg2p_fastapi_common.schemas import G2PResponse, G2PResponseBody, G2PResponseHeader, G2PResponseStatus
    from openg2p_registry_partner_api.ingestion.helpers.request_response_helper import RequestResponseHelper

    assert po.install_partner_json_responses() is True
    assert po.install_partner_json_responses() is True  # idempotent
    response = G2PResponse(
        response_header=G2PResponseHeader(request_id="", response_status=G2PResponseStatus.SUCCESS,
                                          response_error_code="", response_error_message="",
                                          response_timestamp=datetime.datetime(2026, 10, 28, 12, 0, 0)),
        response_body=G2PResponseBody(pagination_response=None, response_payload=None),
    )
    http = RequestResponseHelper._construct_data_model_response(RequestResponseHelper(), None, response)
    assert http.status_code == 200
    assert b"2026-10-28T12:00:00" in http.body


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


def test_worker_engine_uses_null_pool(monkeypatch):
    pytest.importorskip("openg2p_registry_celery_worker")
    from sqlalchemy.pool import NullPool
    from openg2p_registry_celery_worker.engine import Engine

    assert po.install_worker_null_pool() is True
    assert po.install_worker_null_pool() is True  # idempotent
    seen = {}
    monkeypatch.setattr(Engine, "_async_engine", None)
    monkeypatch.setattr(Engine, "construct_async_db_datasource", staticmethod(lambda: "postgresql+asyncpg://u:p@db/x"))
    monkeypatch.setattr(po, "install_worker_null_pool", po.install_worker_null_pool)
    import openg2p_registry_da_extension.platform_overrides as module
    monkeypatch.setattr("sqlalchemy.ext.asyncio.create_async_engine", lambda ds, **kw: seen.update(ds=ds, **kw) or "engine")
    # the override captured create_async_engine at install time; re-install against the patched symbol
    Engine.get_async_engine = Engine.get_async_engine.__func__ if hasattr(Engine.get_async_engine, "__func__") else Engine.get_async_engine
    delattr(Engine.get_async_engine, po._INSTALLED) if hasattr(Engine.get_async_engine, po._INSTALLED) else None
    assert module.install_worker_null_pool() is True
    assert Engine.get_async_engine() == "engine"
    assert seen["poolclass"] is NullPool
