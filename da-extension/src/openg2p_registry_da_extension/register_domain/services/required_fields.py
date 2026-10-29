"""Required fields of the DA form, read from the register metadata.

The section UI schemas (g2p_register_sections.section_ui_schema) say which
widgets are required (widget-required) and what they are called
(widget-label). That is the one place the rule lives: the staff UI marks the
field, the save and finalize checks (da_intake_guard.py) and the domain
validator (g2p_register_domain_service_da.py) read the same flag. Making a
field optional is a metadata change, not a code change.

A widget's data path names the field: "<register_id>.email", or for the geo
widget {"value": "<register_id>.geo_lowest_level_value_id", "hierarchy": ...}.
"""

from __future__ import annotations

import time
from typing import Any

DA_REGISTER_ID = "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90"
_CACHE_SECONDS = 300


def _field_of(path: Any) -> str | None:
    if isinstance(path, str) and path.strip():
        return path.rsplit(".", 1)[-1].strip() or None
    return None


def _fields_of(path: Any) -> list[str]:
    if isinstance(path, dict):
        return [f for f in (_field_of(v) for v in path.values()) if f]
    field = _field_of(path)
    return [field] if field else []


def _walk(node: Any):
    if isinstance(node, dict):
        if "widget-data-path" in node:
            yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def fields_in_schema(section_ui_schema: Any) -> list[str]:
    """Every field a section's widgets write, in widget order."""
    out: list[str] = []
    for widget in _walk(section_ui_schema):
        for field in _fields_of(widget.get("widget-data-path")):
            if field not in out:
                out.append(field)
    return out


def required_fields_in_schema(section_ui_schema: Any) -> dict[str, str]:
    """{field: label} for the widgets a section marks required."""
    out: dict[str, str] = {}
    for widget in _walk(section_ui_schema):
        if widget.get("widget-readonly") or not widget.get("widget-required"):
            continue
        label = str(widget.get("widget-label") or "").strip()
        for field in _fields_of(widget.get("widget-data-path")):
            out.setdefault(field, label or field.replace("_", " ").title())
    return out


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def missing_labels(required: dict[str, str], record: dict, *, absent_is_missing: bool) -> list[str]:
    """Labels of required fields the record does not fill. With
    absent_is_missing a field the record does not mention counts as empty
    (a new record, or a whole submission); without it only fields the
    record sets to blank count (a partial update)."""
    labels: list[str] = []
    for field, label in required.items():
        if field in record:
            if is_blank(record.get(field)) and label not in labels:
                labels.append(label)
        elif absent_is_missing and label not in labels:
            labels.append(label)
    return labels


_cache: dict[str, tuple[float, dict[str, str]]] = {}


def set_required_fields_for_tests(register_id: str, required: dict[str, str] | None) -> None:
    if required is None:
        _cache.pop(register_id, None)
    else:
        _cache[register_id] = (float("inf"), dict(required))


async def load_required_fields(register_id: str = DA_REGISTER_ID) -> dict[str, str]:
    """Required fields across every section of a register, from the DB."""
    hit = _cache.get(register_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    from openg2p_fastapi_common.context import get_async_session_maker
    from openg2p_registry_core.models import G2PRegisterSection
    from sqlalchemy import select

    required: dict[str, str] = {}
    async with get_async_session_maker()() as session:
        rows = (await session.execute(
            select(G2PRegisterSection.section_ui_schema).where(G2PRegisterSection.register_id == register_id)
        )).scalars().all()
    for schema in rows:
        for field, label in required_fields_in_schema(schema).items():
            required.setdefault(field, label)
    _cache[register_id] = (time.monotonic() + _CACHE_SECONDS, required)
    return required
