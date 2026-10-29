"""Service token for unattended approvals: settings resolution and failure modes."""

import pytest

from openg2p_registry_da_extension.register_domain.services import awe_service_token as m


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for k in ("DA_AWE_TOKEN_URL", "DA_AWE_CLIENT_ID", "DA_AWE_CLIENT_SECRET"):
        monkeypatch.delenv(k, raising=False)
    for p in m._PROCESS_PREFIXES:
        for k in ("TOKEN_URL", "CLIENT_ID", "CLIENT_SECRET"):
            monkeypatch.delenv(f"{p}MASTER_DATA_{k}", raising=False)
    m._cache.update({"token": None, "expires_at": 0.0})


def test_explicit_settings_win(monkeypatch):
    monkeypatch.setenv("DA_AWE_TOKEN_URL", "http://kc/token")
    monkeypatch.setenv("DA_AWE_CLIENT_ID", "worker")
    monkeypatch.setenv("DA_AWE_CLIENT_SECRET", "s")
    monkeypatch.setenv("REGISTRY_CELERY_WORKERS_MASTER_DATA_CLIENT_ID", "other")
    assert m.service_token_settings() == {"token_url": "http://kc/token", "client_id": "worker", "client_secret": "s"}


def test_falls_back_to_the_master_data_client_of_the_process(monkeypatch):
    monkeypatch.setenv("REGISTRY_CELERY_WORKERS_MASTER_DATA_TOKEN_URL", "http://kc/token")
    monkeypatch.setenv("REGISTRY_CELERY_WORKERS_MASTER_DATA_CLIENT_ID", "da-registry-backend")
    monkeypatch.setenv("REGISTRY_CELERY_WORKERS_MASTER_DATA_CLIENT_SECRET", "s")
    assert m.service_token_settings()["client_id"] == "da-registry-backend"


@pytest.mark.asyncio
async def test_missing_settings_are_logged_not_shown_to_staff(caplog):
    with pytest.raises(m.ServiceTokenUnavailable) as exc:
        await m.get_service_token()
    assert "DA_AWE" not in str(exc.value) and "Ask an administrator" in str(exc.value)
    assert "DA_AWE_TOKEN_URL" in caplog.text and "missing: token_url, client_id, client_secret" in caplog.text


@pytest.mark.asyncio
async def test_cached_token_is_reused():
    m._cache.update({"token": "cached", "expires_at": 10**12})
    assert await m.get_service_token() == "cached"
