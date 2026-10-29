"""A Development Agent sees and edits only their own DA record.

A DA signs in to DA Services (or the registry portal) with a Keycloak user
that carries the attribute `da_id` (their DA-ID, e.g. DA-3687498303), mapped
into the access token as the claim `da_id`. For such a user, when the only
roles they hold on the registry client are the Development Agent ones (Data
Editor) plus data-policy roles, this module:

1. replaces the request's data policies with one ALLOW policy on the DA
   register, `functional_record_id = <da_id>`. The platform applies data
   policies to register search, record and tab reads and to change-request
   reads, so every one of those returns only the DA's own record
   (REG-ERR-012 RECORD_ACCESS_DENIED for any other record);
2. restricts `create_change_request`, which the platform does not put under
   data policies: the change must target the DA's own record and one of the
   editable sections (contact, service, location; never the identity section).

Any user with a wider role (Intake Officer, Validator, Supervisor, Operations
Administrator, ...) or without the `da_id` claim is untouched and keeps the
Woreda / Region scoping of the data policies. The DA's change request then
goes through the same two-level approval as any other.

Settings (environment):
  DA_SELF_SERVICE_CLAIM      token claim with the DA-ID (default `da_id`)
  DA_SELF_SERVICE_CLIENT_ID  the registry's Keycloak client whose roles are
                             inspected (default `da-registry-staff-portal`)
"""

import base64
import functools
import json
import logging
import os

from sqlalchemy import text

_logger = logging.getLogger("da-own-record")

DA_REGISTER_MNEMONIC = "DA"
SELF_SERVICE_ROLES = {"Data Editor"}  # the Development Agent's registry roles
EDITABLE_SECTIONS = {"da_contact_section_04", "da_service_section_02", "da_location_section_03"}
_INSTALLED_MARKER = "_da_own_record_guard"
_register_id_cache: dict = {}


def _claim_name() -> str:
    return os.environ.get("DA_SELF_SERVICE_CLAIM", "da_id").strip() or "da_id"


def _client_id() -> str:
    return os.environ.get("DA_SELF_SERVICE_CLIENT_ID", "da-registry-staff-portal").strip() or "da-registry-staff-portal"


def _claims(token: str | None) -> dict:
    """The JWT payload, unverified: the platform's auth middleware has already
    validated the token before anything here runs."""
    try:
        part = (token or "").split(".")[1]
        return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    except Exception:
        return {}


def self_service_da_id(token: str | None) -> str | None:
    """The DA-ID when the token belongs to a DA restricted to their own record."""
    claims = _claims(token)
    da_id = str(claims.get(_claim_name()) or "").strip()
    if not da_id:
        return None
    roles = (claims.get("resource_access") or {}).get(_client_id(), {}).get("roles") or []
    wider = [r for r in roles if r not in SELF_SERVICE_ROLES and not str(r).startswith("DP_")]
    return None if wider else da_id


def self_policy(register_id: str, da_id: str) -> dict:
    return {
        "policy_mnemonic": "DP_DA_SELF",
        "policy_description": "A Development Agent sees only their own DA record",
        "register_id": register_id,
        "policy_target": "REGISTER_RECORD",
        "policy_type": "ALLOW",
        "policy_filter_expression": {
            "type": "GROUP",
            "operator": "AND",
            "children": [{"type": "CONDITION", "field_id": "functional_record_id", "operator": "eq", "value": da_id}],
        },
    }


async def _da_register_id() -> str | None:
    if "id" not in _register_id_cache:
        from openg2p_fastapi_common.context import dbengine
        from sqlalchemy.ext.asyncio import async_sessionmaker

        async with async_sessionmaker(dbengine.get(), expire_on_commit=False)() as session:
            _register_id_cache["id"] = (
                await session.execute(
                    text("SELECT register_id FROM g2p_register_definitions WHERE register_mnemonic = :m"),
                    {"m": DA_REGISTER_MNEMONIC},
                )
            ).scalar_one_or_none()
    return _register_id_cache["id"]


def _bearer(request, auth_state_key: str) -> str | None:
    auth = getattr(request.state, auth_state_key, None)
    token = getattr(auth, "credentials", None) or getattr(auth, "access_token", None)
    if not token:
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else None
    return token


async def apply_self_policy(request, policies_state_key: str, auth_state_key: str) -> None:
    da_id = self_service_da_id(_bearer(request, auth_state_key))
    if not da_id:
        return
    register_id = await _da_register_id()
    if not register_id:
        return
    # Replace, not append: ALLOW policies are unioned, so a Woreda policy on the
    # same user would otherwise widen the DA's view to the whole Woreda.
    setattr(request.state, policies_state_key, [self_policy(register_id, da_id)])
    _logger.debug("Self-service data policy applied for %s on %s", da_id, request.url.path)


def _access_denied(message: str):
    from openg2p_registry_core.errors import G2PRegistryErrorCodes, G2PRegistryException

    return G2PRegistryException(code=G2PRegistryErrorCodes.RECORD_ACCESS_DENIED.value[1], message=message)


async def check_own_change_request(payload, da_id: str) -> None:
    """Raise unless the change request targets the DA's own record and an editable section."""
    section_id = str(getattr(payload, "section_id", "") or "")
    if section_id not in EDITABLE_SECTIONS:
        raise _access_denied("A Development Agent may change only their contact, service and location details")
    record_ids = {str(getattr(payload, "internal_record_id", "") or "")}
    for item in getattr(payload, "change_payload", None) or []:
        rid = item.get("internal_record_id") if isinstance(item, dict) else getattr(item, "internal_record_id", None)
        if rid:
            record_ids.add(str(rid))
    record_ids.discard("")
    if len(record_ids) != 1:
        raise _access_denied("A Development Agent may change only their own record")
    from openg2p_fastapi_common.context import dbengine
    from sqlalchemy.ext.asyncio import async_sessionmaker

    async with async_sessionmaker(dbengine.get(), expire_on_commit=False)() as session:
        functional_id = (
            await session.execute(
                text("SELECT functional_record_id FROM g2p_register_das WHERE internal_record_id = :rid"),
                {"rid": record_ids.pop()},
            )
        ).scalar_one_or_none()
    if functional_id != da_id:
        raise _access_denied("A Development Agent may change only their own record")


def _wrap_dispatch(dispatch):
    @functools.wraps(dispatch)
    async def wrapper(self, request, call_next):
        async def call_next_with_self_policy(req):
            try:
                await apply_self_policy(req, self.policies_state_key, self.auth_state_key)
            except Exception:  # never block a request because of the guard itself
                _logger.exception("DA self-service policy could not be applied")
            return await call_next(req)

        return await dispatch(self, request, call_next_with_self_policy)

    setattr(wrapper, _INSTALLED_MARKER, True)
    return wrapper


def _wrap_create_change_request(create):
    @functools.wraps(create)
    async def wrapper(self, change_request_request, *args, **kwargs):
        da_id = self_service_da_id(kwargs.get("bearer_token"))
        if da_id:
            await check_own_change_request(change_request_request.request_body.request_payload, da_id)
        return await create(self, change_request_request, *args, **kwargs)

    setattr(wrapper, _INSTALLED_MARKER, True)
    return wrapper


def install_da_own_record_guard() -> None:
    """Idempotent. Staff API only: the partner API has no user tokens."""
    try:
        from iam_core.user_auth.middleware.data_policy import DataPolicyMiddleware
    except ImportError:
        return
    if not getattr(DataPolicyMiddleware.dispatch, _INSTALLED_MARKER, False):
        DataPolicyMiddleware.dispatch = _wrap_dispatch(DataPolicyMiddleware.dispatch)
    from openg2p_registry_core.controller_services import G2PRegisterChangerequestControllerService

    method = getattr(G2PRegisterChangerequestControllerService, "create_change_request", None)
    if method is None:
        raise AttributeError("G2PRegisterChangerequestControllerService.create_change_request no longer exists; re-anchor the DA own-record guard")
    if not getattr(method, _INSTALLED_MARKER, False):
        G2PRegisterChangerequestControllerService.create_change_request = _wrap_create_change_request(method)
    _logger.info("DA own-record guard installed (claim %s, client %s)", _claim_name(), _client_id())
