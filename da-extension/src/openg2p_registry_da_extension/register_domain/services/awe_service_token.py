"""Service token for the approval workflow of unattended DA submissions.

A DA that arrives by file import or partner ingestion is finalised by a celery
worker, which has no signed-in user and so no bearer token to open the AWE
approval request with (the platform raises AWE_BEARER_TOKEN_REQUIRED). AWE
accepts a Keycloak client-credentials token for service-to-service calls, so
this module fetches one and `auto_approve.py` passes it to the platform's
workflow start. The approvers are then resolved by the seeded rules exactly as
for a web-form submission.

Settings (environment):
  DA_AWE_TOKEN_URL      Keycloak token endpoint of the staff realm
  DA_AWE_CLIENT_ID      a confidential client with service accounts enabled
  DA_AWE_CLIENT_SECRET  its secret
When unset, the Master Data client of the running process is used
(REGISTRY_<PROCESS>_MASTER_DATA_TOKEN_URL / _CLIENT_ID / _CLIENT_SECRET): in
every DA deployment that is `da-registry-backend`, a confidential client that
already exists for the Master Data calls.
"""

import logging
import os
import time

import httpx

_logger = logging.getLogger("da-awe-service-token")

_PROCESS_PREFIXES = (
    "REGISTRY_CELERY_WORKERS_",
    "REGISTRY_PARTNER_API_",
    "REGISTRY_STAFF_PORTAL_API_",
)
_cache: dict = {"token": None, "expires_at": 0.0}


def _fallback(suffix: str) -> str:
    for prefix in _PROCESS_PREFIXES:
        value = os.environ.get(f"{prefix}MASTER_DATA_{suffix}", "").strip()
        if value:
            return value
    return ""


def service_token_settings() -> dict:
    return {
        "token_url": os.environ.get("DA_AWE_TOKEN_URL", "").strip() or _fallback("TOKEN_URL"),
        "client_id": os.environ.get("DA_AWE_CLIENT_ID", "").strip() or _fallback("CLIENT_ID"),
        "client_secret": os.environ.get("DA_AWE_CLIENT_SECRET", "").strip() or _fallback("CLIENT_SECRET"),
    }


class ServiceTokenUnavailable(RuntimeError):
    pass


async def get_service_token() -> str:
    """A cached client-credentials access token; raises ServiceTokenUnavailable
    with a message that names the missing setting or the Keycloak error."""
    if _cache["token"] and time.time() < _cache["expires_at"] - 30:
        return _cache["token"]
    cfg = service_token_settings()
    missing = [k for k, v in cfg.items() if not v]
    if missing:
        raise ServiceTokenUnavailable(
            "DA approval service token is not configured: set DA_AWE_TOKEN_URL, "
            "DA_AWE_CLIENT_ID and DA_AWE_CLIENT_SECRET (missing: " + ", ".join(missing) + ")"
        )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                cfg["token_url"],
                data={
                    "grant_type": "client_credentials",
                    "client_id": cfg["client_id"],
                    "client_secret": cfg["client_secret"],
                },
            )
    except httpx.HTTPError as exc:
        raise ServiceTokenUnavailable(f"Keycloak token request failed: {exc}") from exc
    if resp.status_code >= 400:
        raise ServiceTokenUnavailable(f"Keycloak refused the service token ({resp.status_code}): {resp.text[:200]}")
    payload = resp.json()
    _cache["token"] = payload["access_token"]
    _cache["expires_at"] = time.time() + int(payload.get("expires_in", 300))
    _logger.info("DA approval service token obtained for client %s", cfg["client_id"])
    return _cache["token"]
