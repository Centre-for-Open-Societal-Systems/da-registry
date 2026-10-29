"""TEMPORARY overrides of OpenG2P platform behaviour, kept on the user's decision of 29 Oct 2026.

Each one replaces a method of a platform class in the running process, because
the platform offers no configuration or registration hook for it (checked on
registry-platform 1.2.2-rc.614: none of these classes is a registered
component, and none of the behaviours is a setting). The platform files on disk
are untouched. Every override is idempotent and skips cleanly when the platform
package it targets is not in the process. Remove each one when OpenG2P fixes
it; docs/refactor/platform-overrides.md lists them with the re-check steps.

Removed on 29 Oct 2026:
- FilterBuilder accepting "true"/"false" strings: no DA filter is boolean, so
  it never applied.
- The celery worker NullPool engine: a 12-row import measured the same with
  and without it (all rows in approval in ~116 s, two "attached to a
  different loop" errors that the platform retries); the error comes from
  elsewhere in the platform and is reported upstream instead.
- The DataPolicyMiddleware own-record policy: a Development Agent's access to
  only their own record is enforced by DA Services, which calls the registry
  with its service account (docs/rbac-registry-roles.md section 5).

Everything else this extension changes in the platform goes through the
component registry (subclass registered ahead of the platform service); this
module is the only place that reassigns platform methods.

1. IAM permission lookup (staff API) - install_scoped_permission_lookup
   Bug: the platform asks IAM `get_permissions_for_roles` with bare role names,
   and IAM answers with the first active role of that name across every
   registered application. On a cluster hosting several registries the roles
   share names, so a user's permissions come from whichever application sorts
   first. The override asks `get_application_permissions_for_user` for this
   application only.
   Platform version checked: 1.2.2-rc.614, IAM 1.4.2 (the IAM service still
   looks a role up by name only, first match).
   Without it: users get another registry's permissions (too many or too few).
   Remove when OpenG2P fixes it.

2. Record history change source (staff API) - install_history_change_request_source
   Bug: the platform maps register history change_request_source as String,
   but G2PRegisterService.get_record_history reads `.value` on it, so every
   history call fails with "'str' object has no attribute 'value'"
   (SYS-ERR-001 on every tab). This is not a method reassignment: one load
   listener on G2PRegisterHistory converts the stored text to the platform's
   ChangeRequestSourceEnum (a StrEnum, so it still equals and serialises as
   the text) without marking the row changed.
   Platform version checked: 1.2.2-rc.614 (registry-platform develop has the
   same code).
   Without it: the History view shows an error instead of the changes.
   Remove when OpenG2P fixes it.
"""

import contextvars
import functools
import logging

_logger = logging.getLogger("da-temporary-platform-overrides")
_INSTALLED = "_da_platform_override"

# ------------------------------------------------------------ 1. permissions

_current_request: contextvars.ContextVar = contextvars.ContextVar("da_current_request", default=None)


def permissions_for_application(applications, client_id: str) -> set[str]:
    """The permissions IAM reports for this client only."""
    permissions: set[str] = set()
    for application in applications or []:
        if (application or {}).get("application_mnemonic") == client_id:
            permissions.update(application.get("permissions") or [])
    return permissions


def install_scoped_permission_lookup() -> bool:
    try:
        import httpx
        from iam_core.user_auth.middleware.resolve_permissions import ResolvePermissionMiddleware
        from openg2p_fastapi_common.errors.http_exceptions import ForbiddenError
    except ImportError:
        return False
    if getattr(ResolvePermissionMiddleware.dispatch, _INSTALLED, False):
        return True

    original_dispatch = ResolvePermissionMiddleware.dispatch
    original_fetch = ResolvePermissionMiddleware._fetch_permissions_for_roles

    @functools.wraps(original_dispatch)
    async def dispatch(self, request, call_next):
        token = _current_request.set(request)
        try:
            return await original_dispatch(self, request, call_next)
        finally:
            _current_request.reset(token)

    @functools.wraps(original_fetch)
    async def _fetch_permissions_for_roles(self, role_mnemonics):
        auth_provider_api_url = (self._config.auth_provider_api_url or "").strip()
        if not auth_provider_api_url:
            raise ForbiddenError(message="Forbidden. auth_provider_api_url is not configured.")
        if not role_mnemonics:
            return set()
        request = _current_request.get()
        principal = getattr(request.state, self._state_key, None) if request is not None else None
        client_id = (self._client_id or "").strip()
        credentials = getattr(principal, "credentials", None)
        if not credentials or not client_id:
            raise ForbiddenError(message="Forbidden. Unable to fetch user permissions.")
        endpoint = auth_provider_api_url.rstrip("/") + "/user-access/get_application_permissions_for_user"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    endpoint,
                    params={"application_mnemonic": client_id},
                    headers={"Authorization": f"Bearer {credentials}"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ForbiddenError(message="Forbidden. Unable to fetch user permissions.") from exc
        return permissions_for_application(response.json(), client_id)

    setattr(dispatch, _INSTALLED, True)
    setattr(_fetch_permissions_for_roles, _INSTALLED, True)
    ResolvePermissionMiddleware.dispatch = dispatch
    ResolvePermissionMiddleware._fetch_permissions_for_roles = _fetch_permissions_for_roles
    _logger.info("IAM permissions resolved per application (platform cross-registry lookup fix)")
    return True


# ------------------------------------------------ 2. record history source


def as_change_request_source(target) -> None:
    """Stored change_request_source text as the platform enum, left as stored if unknown."""
    try:
        from openg2p_registry_core.models.enum import ChangeRequestSourceEnum
        from sqlalchemy.orm.attributes import set_committed_value
    except ImportError:
        return
    value = getattr(target, "change_request_source", None)
    if not isinstance(value, str) or isinstance(value, ChangeRequestSourceEnum):
        return
    try:
        set_committed_value(target, "change_request_source", ChangeRequestSourceEnum(value))
    except ValueError:
        _logger.warning("Unknown change request source %r on %s", value, type(target).__name__)


def _history_loaded(target, _context) -> None:
    as_change_request_source(target)


def install_history_change_request_source() -> bool:
    try:
        from openg2p_registry_core.models import G2PRegisterHistory
        from sqlalchemy import event
    except ImportError:
        return False
    if not event.contains(G2PRegisterHistory, "load", _history_loaded):
        event.listen(G2PRegisterHistory, "load", _history_loaded, propagate=True)
        _logger.info("Register history change_request_source loaded as the platform enum (record history fix)")
    return True


def install_temporary_platform_overrides() -> None:
    install_scoped_permission_lookup()
    install_history_change_request_source()
