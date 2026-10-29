"""Fixes for two platform bugs, installed at start-up inside this extension.

They used to be text patches applied to the platform's files at image build
time (docker/patches/patch_platform.py). The registry standards of 27-28 Oct
2026 rule that out: the platform images stay as published and a registry only
adds its extension. The same fixes are therefore applied here, in the
running process, by replacing the platform method concerned; the platform
package on disk is untouched. Each installer is idempotent and skips cleanly
when the platform package it targets is not present in the process (the
IAM fix in the staff API, the worker fix in the celery worker, ...).

Drop an installer once the fix has landed in the platform image that
RP_VERSION points at (checked on 1.2.2-rc.557: both are still needed).

Partner API ingest replies are not fixed here: the data models in
meta_data/data-models/data_models.sql carry the DCI response template, which
is what makes the platform serialise the reply.

1. IAM permission lookup: the platform asks IAM `get_permissions_for_roles`
   with bare role names, and IAM answers with the first active role of that
   name across every registered application. On a cluster hosting several
   registries the roles share names, so a user's permissions come from
   whichever application sorts first. `get_application_permissions_for_user`
   resolves the caller's roles inside this application only.
2. Celery worker database engine: one pooled async engine per process, but
   each task module runs on its own event loop; asyncpg binds a connection to
   the loop it was opened on, so a pooled connection handed from one task
   type to another fails with "attached to a different loop" and valid records
   get stuck behind an invalid one. NullPool opens a fresh connection per
   session, as the platform's newer activity worker does.
"""

import contextvars
import functools
import logging

_logger = logging.getLogger("da-platform-overrides")
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


# ----------------------------------------------------------------- 2. worker


def install_worker_null_pool() -> bool:
    try:
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool
        from openg2p_registry_celery_worker.engine import Engine
    except ImportError:
        return False
    if getattr(Engine.get_async_engine, _INSTALLED, False):
        return True

    def get_async_engine():
        if Engine._async_engine is None:
            datasource = Engine.construct_async_db_datasource()
            try:
                Engine._async_engine = create_async_engine(datasource, poolclass=NullPool)
            except Exception as e:  # same message as the platform's
                raise ValueError(f"Invalid DB datasource: {datasource} | ERROR: {e}")
        return Engine._async_engine

    setattr(get_async_engine, _INSTALLED, True)
    Engine.get_async_engine = staticmethod(get_async_engine)
    _logger.info("Celery worker async engine uses NullPool (platform event-loop fix)")
    return True


def install_platform_overrides() -> None:
    install_scoped_permission_lookup()
    install_worker_null_pool()
