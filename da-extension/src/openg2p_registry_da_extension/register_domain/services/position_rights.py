"""Who may give a position, and who may change it.

The register holds everyone: development agents and the people they report to,
up to the administrator. A person's position decides the rights of the
Keycloak account the registry makes for them, so the position cannot be a free
choice of whoever fills in the form: a supervisor who could register an
administrator could make themselves one.

The rules are on the widgets of the section metadata, so they are configuration:

  "oan-value-rights": {"open": ["DEVELOPMENT_AGENT", "SENIOR_DA"],
                       "roles": ["Operations Administrator"],
                       "permission": "incomingMessage:view"}
      Values outside "open" can be given only by a user with one of "roles"
      (a registry role, as the token carries it). "permission" is what the
      form uses to leave those values out of the dropdown for everyone else
      (the staff UI knows a user's permissions, not their roles); this module
      does not read it.

  "oan-change-roles": ["Intake Officer", "Data Supervisor", "Operations Administrator"]
      Changing the field on a registered record needs one of these roles. A
      development agent, who has "Data Editor" only, cannot change their own
      position or the person they report to.

Where they apply:

- A save or a change request through the staff API: the caller's roles are the
  ones of the registry's Keycloak client in their token.
- A file import or a DA Services push (no caller): a value outside "open" is
  refused. Such a person is registered in the registry by an administrator.
- A record on its way from an approved submission to the register (the celery
  worker, no caller, not from another system): not checked again; it was
  checked when it was saved.

A field that is sent with the value the register already has is not a change
and is never refused: a supervisor can still correct an administrator's phone
number, the form sends the whole section.

Which record "the register already has" is the one the change request is for
(ChangeTargetMixin keeps its id for the length of the call), never the id a
payload row names: the platform applies a row to the request's record whatever
id the row carries, so a row naming another record, or none, would otherwise
be compared with the wrong record or pass as new. Outside a change request (a
form save) nothing is "as it is": every record is checked as new.
"""

from __future__ import annotations

import contextvars
import os
from typing import Any

from sqlalchemy import text

from .domain_validation_utils import validation_error
from .required_fields import _field_of, _walk, came_from_another_system, is_blank

VALUE_RIGHTS = "oan-value-rights"
CHANGE_ROLES = "oan-change-roles"

# The id of the record the change request being created is for; None outside one.
_change_target: contextvars.ContextVar = contextvars.ContextVar("da_change_target", default=None)


class ChangeTargetMixin:
    """Placed ahead of the platform's change request service: remembers which
    record a change request is for while it is created, for check() below."""

    async def create_change_request(self, change_request_request_payload, *args, **kwargs):
        target = str(getattr(change_request_request_payload, "internal_record_id", None) or "")
        token = _change_target.set(target)
        try:
            return await super().create_change_request(change_request_request_payload, *args, **kwargs)
        finally:
            _change_target.reset(token)


def field_rules(sections: list) -> dict[str, dict]:
    """{field: {"label", "open", "roles", "change_roles"}} for the fields whose
    widgets carry a rule. "open" is None when every value is open."""
    rules: dict[str, dict] = {}
    for _name, schema, is_list in sections:
        if is_list:
            continue
        for widget in _walk(schema):
            rights = widget.get(VALUE_RIGHTS)
            change = widget.get(CHANGE_ROLES)
            if not isinstance(rights, dict) and not isinstance(change, list):
                continue
            path = widget.get("widget-data-path")
            field = _field_of(path) if isinstance(path, str) else None
            if not field or field in rules:
                continue
            rights = rights if isinstance(rights, dict) else {}
            rules[field] = {
                "label": str(widget.get("widget-label") or field).strip(),
                "open": {str(v) for v in rights["open"]} if isinstance(rights.get("open"), list) else None,
                "roles": {str(r) for r in rights.get("roles") or []},
                "change_roles": {str(r) for r in change} if isinstance(change, list) else None,
            }
    return rules


def caller_roles() -> set[str] | None:
    """The registry roles of the user behind the current staff API request;
    None when there is no request (a worker). A request whose user cannot be
    read has no roles, so the rules fail closed."""
    try:
        from ..temporary_platform_overrides import _current_request
    except ImportError:
        return None
    request = _current_request.get()
    if request is None:
        return None
    principal = getattr(getattr(request, "state", None), "auth", None)
    by_client = getattr(principal, "client_roles", None) or {}
    if not isinstance(by_client, dict):
        return set()
    # Only the roles of the registry's own client count: a role of the same
    # name on another application's client gives no right here. Without the
    # client id nobody has a role, which an administrator notices at once.
    client_id = registry_client_id()
    return {str(r) for r in by_client.get(client_id) or []} if client_id else set()


def registry_client_id() -> str:
    """The Keycloak client whose roles are the registry's: the staff API's
    setting, from its environment or the running application's configuration."""
    value = os.environ.get("REGISTRY_STAFF_PORTAL_API_KEYCLOAK_CLIENT_ID", "").strip()
    if value:
        return value
    try:
        from ...config import Settings

        return str(getattr(Settings.get_config(), "keycloak_client_id", "") or "").strip()
    except Exception:  # noqa: BLE001 - no configuration: no client, no roles
        return ""


def _same(a: Any, b: Any) -> bool:
    if is_blank(a) and is_blank(b):
        return True
    return str(a) == str(b)


def request_problem(
    record: dict, rules: dict[str, dict], roles: set[str], stored: dict | None, changing: bool | None = None
) -> str | None:
    """Why this caller may not save the record, or None. `stored` is the
    current values, in the register, of the record a change request is for;
    None for a form save or a record that is not registered. `changing` says
    the save is a change request (by default: whenever `stored` is given)."""
    changing = stored is not None if changing is None else changing
    for field, rule in rules.items():
        if field not in record:
            continue
        value = record.get(field)
        if stored is not None and _same(stored.get(field), value):
            continue  # sent as it is: not a change
        if changing and rule["change_roles"] is not None and not (roles & rule["change_roles"]):
            return f"{rule['label']}: you cannot change this. Ask your supervisor to change it."
        if rule["open"] is not None and not is_blank(value) and str(value) not in rule["open"] \
                and not (roles & rule["roles"]):
            return (
                f"{rule['label']}: only an administrator can give this position ({value}). "
                "Choose another position, or ask an administrator to register this person."
            )
    return None


def import_problem(record: dict, sections: list) -> str | None:
    """Why a file row or a DA Services record is refused, or None."""
    for field, rule in field_rules(sections).items():
        value = record.get(field)
        if rule["open"] is not None and not is_blank(value) and str(value) not in rule["open"]:
            return (
                f"{rule['label']}: {value} cannot be given in a file import or by DA Services. "
                "An administrator registers this person in the registry."
            )
    return None


async def _stored(internal_record_id: Any, fields: list[str]) -> dict | None:
    """The registered record's values of these fields; None when the record is
    not in the register (a new submission)."""
    if not internal_record_id or not fields:
        return None
    from openg2p_fastapi_common.context import dbengine

    columns = ", ".join(f'"{name}"' for name in fields if name.replace("_", "").isalnum())
    if not columns:
        return None
    async with dbengine.get().connect() as conn:
        row = (
            await conn.execute(
                text(f'SELECT {columns} FROM "public"."g2p_register_das" WHERE "internal_record_id" = :id'),
                {"id": str(internal_record_id)},
            )
        ).mappings().first()
    return dict(row) if row else None


async def check(record: dict, sections: list) -> None:
    """Refuse a record that gives or changes a ruled field against the rules."""
    rules = field_rules(sections)
    touched = [field for field in rules if field in record]
    if not touched:
        return
    roles = caller_roles()
    if roles is None:
        if came_from_another_system(record):
            message = import_problem(record, sections)
            if message:
                validation_error(message)
        return
    target = _change_target.get()
    stored = await _stored(target, list(rules)) if target else None
    message = request_problem(record, rules, roles, stored, changing=target is not None)
    if message:
        validation_error(message)
