#!/usr/bin/env python3
"""Overlay fixes for the pinned registry-platform images.

Each entry patches a bug that the pinned platform ships: the IAM permission
lookup in iam_core, the partner API's ingest response, and the celery worker's
database pool shared across event loops. (The registry-core async/await fixes
this script used to carry are in the platform since develop.604 and 1.2.) Applied at
image build time to every stage that installs registry-core (staff-api,
partner-api, celery), because the same packages are present in all of them; a
patch whose file is absent from a stage is skipped.

Drop an entry here once the corresponding fix lands in the platform image the
RP_VERSION pin points at -- the script fails loudly if a patch stops matching,
so a stale entry surfaces on the next build rather than rotting silently.

PATCH_PLATFORM_SITE_PACKAGES overrides the target directory so the patches can
be exercised against a copy of the sources outside an image (test/).
"""

from __future__ import annotations

import os
import pathlib
import sys

SITE_PACKAGES = pathlib.Path(
    os.environ.get(
        "PATCH_PLATFORM_SITE_PACKAGES", "/usr/local/lib/python3.12/site-packages"
    )
)


class Patch:
    def __init__(self, relative_path: str, old: str, new: str, why: str):
        self.path = SITE_PACKAGES / relative_path
        self.old = old
        self.new = new
        self.why = why


PATCHES = [
    Patch(
        "openg2p_registry_partner_api/ingestion/helpers/request_response_helper.py",
        old="            return JSONResponse(content=response.model_dump())",
        new='            return JSONResponse(content=response.model_dump(mode="json"))',
        why=(
            "The partner ingest success response carries response_timestamp as a "
            "datetime; model_dump() leaves it a datetime and JSONResponse fails with "
            "'Object of type datetime is not JSON serializable', so every "
            "POST /partner/ingest_data answered HTTP 500 although the record had "
            "been accepted. mode='json' serialises it."
        ),
    ),
    Patch(
        "openg2p_registry_partner_api/ingestion/helpers/request_response_helper.py",
        old="        response_data = response.model_dump()\n",
        new='        response_data = response.model_dump(mode="json")\n',
        why="Same datetime problem on the templated response path.",
    ),
    Patch(
        "iam_core/user_auth/middleware/resolve_permissions.py",
        old='''    async def _fetch_permissions_for_roles(self, role_mnemonics: list[str]) -> set[str]:
        """Resolve role mnemonics to permission strings via the auth provider API."""
        auth_provider_api_url = (self._config.auth_provider_api_url or "").strip()
        if not auth_provider_api_url:
            raise ForbiddenError(message="Forbidden. auth_provider_api_url is not configured.")

        if not role_mnemonics:
            return set()

        endpoint = auth_provider_api_url.rstrip("/") + "/user-access/get_permissions_for_roles"

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint,
                    json={"role_mnemonics": role_mnemonics},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ForbiddenError(message="Forbidden. Unable to fetch user permissions.") from exc

        response_data = response.json() or {}
        return set(response_data.get("permissions") or [])
''',
        new='''    async def _fetch_permissions_for_roles(
        self,
        role_mnemonics: list[str],
        principal: AuthPrincipal | None = None,
        client_id: str | None = None,
    ) -> set[str]:
        """Resolve the caller's permissions on THIS application via the auth provider API.

        Patched by da-registry (docker/patches/patch_platform.py): the platform
        asks IAM `get_permissions_for_roles` with bare role names, and IAM answers
        with the first active role of that name across EVERY registered application.
        On a cluster hosting several registries (farmer, livestock, cropsown, a stale
        `registry-staff-portal`) the roles share names, so a user's permissions
        silently come from whichever application's row sorts first -- and if that
        one carries older permission mnemonics, every endpoint answers 403. IAM's
        `get_application_permissions_for_user?application_mnemonic=<client_id>`
        resolves the same token's roles inside one application only, so that is
        what we call, and we keep only the entry for our own client.
        """
        auth_provider_api_url = (self._config.auth_provider_api_url or "").strip()
        if not auth_provider_api_url:
            raise ForbiddenError(message="Forbidden. auth_provider_api_url is not configured.")

        if not role_mnemonics:
            return set()

        if principal is None or not principal.credentials or not client_id:
            raise ForbiddenError(message="Forbidden. Unable to fetch user permissions.")

        endpoint = auth_provider_api_url.rstrip("/") + "/user-access/get_application_permissions_for_user"

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    endpoint,
                    params={"application_mnemonic": client_id},
                    headers={"Authorization": f"Bearer {principal.credentials}"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ForbiddenError(message="Forbidden. Unable to fetch user permissions.") from exc

        permissions: set[str] = set()
        for application in response.json() or []:
            if (application or {}).get("application_mnemonic") == client_id:
                permissions.update(application.get("permissions") or [])
        return permissions
''',
        why=(
            "IAM's get_permissions_for_roles matches roles by name across all "
            "registered applications, so same-named roles of another registry "
            "(or a stale one) decide this registry's permissions. Resolve them "
            "per application with get_application_permissions_for_user instead."
        ),
    ),
    Patch(
        "iam_core/user_auth/middleware/resolve_permissions.py",
        old="            user_permissions = await self._fetch_permissions_for_roles(user_roles)\n",
        new=(
            "            user_permissions = await self._fetch_permissions_for_roles(\n"
            "                user_roles, principal, client_id\n"
            "            )\n"
        ),
        why="Hand the caller's token and this service's client id to the scoped lookup above.",
    ),
    Patch(
        "openg2p_registry_celery_worker/engine.py",
        old="from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine\n",
        new=(
            "from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine\n"
            "from sqlalchemy.pool import NullPool\n"
        ),
        why="Import for the NullPool patch below.",
    ),
    Patch(
        "openg2p_registry_celery_worker/engine.py",
        old="                Engine._async_engine = create_async_engine(datasource, **_pool_kwargs(datasource))\n",
        new="                Engine._async_engine = create_async_engine(datasource, poolclass=NullPool)\n",
        why=(
            "The worker keeps one async engine (one connection pool) per process, but "
            "every task module runs its tasks on its own event loop. asyncpg binds a "
            "connection to the loop it was opened on, so a pooled connection handed "
            "from one task type to another fails with 'attached to a different loop' "
            "(and 'unknown protocol state'); this surfaced as valid records stuck "
            "after an invalid one and the wrong reason saved on failures. NullPool "
            "opens a fresh connection per session, so none outlives its loop -- the "
            "same approach the platform's newer activity_worker takes. Only the "
            "worker image has this file; the APIs keep their pool."
        ),
    ),
]


def main() -> int:
    applied = 0
    for patch in PATCHES:
        if not patch.path.exists():
            print(f"[patch-platform] SKIP (no such file): {patch.path}")
            continue

        source = patch.path.read_text()
        count = source.count(patch.old)

        if count == 0:
            if patch.new in source:
                print(f"[patch-platform] already applied: {patch.path.name}")
                continue
            print(
                f"[patch-platform] FAILED: no match for {patch.old!r} in "
                f"{patch.path.name}. The pinned platform likely changed -- "
                f"re-check whether this patch is still needed.",
                file=sys.stderr,
            )
            return 1

        if count != 1:
            print(
                f"[patch-platform] FAILED: expected exactly one match for "
                f"{patch.old!r} in {patch.path.name}, found {count}.",
                file=sys.stderr,
            )
            return 1

        patch.path.write_text(source.replace(patch.old, patch.new))
        print(f"[patch-platform] applied to {patch.path.name}: {patch.why}")
        applied += 1

    print(f"[patch-platform] {applied} patch(es) applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
