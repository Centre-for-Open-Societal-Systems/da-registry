#!/usr/bin/env python3
"""Seed IAM with registry staff portal applications and RBAC catalogs.

Production registries self-register via POST /user-access/staff_portal_applications
during Helm install. Local dev uses this script after ``make iam-init`` so variant
Keycloak client IDs (for example da-registry-staff-portal) exist in IAM with
roles and permissions.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any


def _load_env_file(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _parse_variants(raw: str) -> list[tuple[str, str]]:
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("REGISTRY_IAM_VARIANTS must be a JSON array")

    variants: list[tuple[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Each REGISTRY_IAM_VARIANTS entry must be an object")
        mnemonic = item.get("mnemonic")
        url = item.get("url")
        if not mnemonic or not url:
            raise ValueError("Each REGISTRY_IAM_VARIANTS entry needs mnemonic and url")
        variants.append((str(mnemonic), str(url)))
    return variants


async def _register_variants(
    catalog: dict[str, Any],
    variants: list[tuple[str, str]],
) -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from iam_staff_portal_api.config import Settings
    from iam_staff_portal_api.controllers.user_access_controller import UserAccessController
    from iam_staff_portal_api.schemas import RegisterStaffPortalApplicationRequest
    from openg2p_fastapi_common.context import dbengine

    config = Settings.get_config(strict=False)
    existing_engine = dbengine.get()
    if existing_engine is not None:
        await existing_engine.dispose(close=False)
    dbengine.set(create_async_engine(config.db_datasource, echo=config.db_logging))

    controller = UserAccessController()

    for mnemonic, url in variants:
        payload_data = dict(catalog)
        payload_data["application_mnemonic"] = mnemonic
        payload_data["application_url"] = url
        payload = RegisterStaffPortalApplicationRequest.model_validate(payload_data)

        response = await controller.register_staff_portal_application(
            None,
            payload,
        )
        action = "created" if response.created else "updated"
        print(
            f"[iam-register] {action} {mnemonic} "
            f"({response.permissions_count} permissions, {response.roles_count} roles)"
        )

    await dbengine.get().dispose(close=False)


def main() -> int:
    payload_path = Path(os.environ.get("REGISTRY_IAM_PAYLOAD", "")).expanduser()
    variants_raw = os.environ.get("REGISTRY_IAM_VARIANTS", "[]")

    if not payload_path.is_file():
        print(f"[iam-register] Missing catalog payload: {payload_path}", file=sys.stderr)
        return 1

    try:
        catalog = json.loads(payload_path.read_text(encoding="utf-8"))
        variants = _parse_variants(variants_raw)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[iam-register] Invalid seed input: {exc}", file=sys.stderr)
        return 1

    if not variants:
        print("[iam-register] No registry variants to register.", file=sys.stderr)
        return 1

    env_file = os.environ.get("IAM_STAFF_ENV_FILE")
    if env_file:
        _load_env_file(Path(env_file))

    try:
        asyncio.run(_register_variants(catalog, variants))
    except Exception as exc:
        print(f"[iam-register] Failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
