"""Required fields of the DA form, read from the register metadata.

The section UI schemas (g2p_register_sections.section_ui_schema) say which
widgets are required (widget-required) and what they are called
(widget-label). That is the one place the rule lives: the staff UI marks the
field, the save and finalize checks (required_fields_mixin.py) and the domain
validator (g2p_register_domain_service_da.py) read the same flag. Making a
field optional is a metadata change, not a code change.

A widget may also carry widget-data-options.actions, a list of
{"action": "show" | "hide" | "require", "condition": {...}}. A hidden widget
is never required; a "require" action makes a widget required while its
condition holds. A condition is {"field", "operator", "value"} (operators
equals, notEquals, in, notIn, empty, notEmpty, contains) or a group
{"and": [...]}, {"or": [...]}, {"not": {...}}.

Two keys of OAN's own:

- "oan-optional-on-import": true on a required widget: the field is required
  of someone filling in the form, and may be left out of a file import or a
  DA Services push (see came_from_another_system).
- A list section's table may carry "require" actions that name a field of the
  parent record, for example "a development agent needs an education record,
  an administrator does not" (see list_requires_row).

Limits: on a web save or finalize a condition is evaluated against the record
of its own section, so a condition naming a field of another section sees no
value (the enrichers pass the whole record and are not affected; a list
section's table is given the parent record). Section schemas are cached for
five minutes, so a metadata edit reaches a running pod within that time.

A widget's data path names the field: "<register_id>.email", or for the geo
widget {"value": "<register_id>.geo_lowest_level_value_id", "hierarchy": ...}.
"""

from __future__ import annotations

import json
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
            out.setdefault(field, label or field.replace("_", " ").capitalize())
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




# --------------------------------------------------------------- conditions --
def _lookup(record: dict, path: Any) -> Any:
    """A condition's field is a path such as "<register>.species"; the record
    is flat, so the last segment names the value."""
    if not isinstance(path, str):
        return None
    if path in record:
        return record.get(path)
    return record.get(path.rsplit(".", 1)[-1])


def _same(a: Any, b: Any) -> bool:
    if is_blank(a) and is_blank(b):
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return str(a).lower() == str(b).lower()
    return a == b or str(a) == str(b)


def evaluate_condition(condition: Any, record: dict) -> bool | None:
    """Whether a widget condition holds for the record; None when the condition
    uses something this evaluator does not know (callers then lean towards
    checking the field)."""
    if not isinstance(condition, dict):
        return None
    for key in ("and", "or"):
        if isinstance(condition.get(key), list):
            results = [evaluate_condition(c, record) for c in condition[key]]
            if key == "and":
                if any(r is False for r in results):
                    return False
                return None if any(r is None for r in results) else True
            if any(r is True for r in results):
                return True
            return None if any(r is None for r in results) else False
    if "not" in condition:
        inner = evaluate_condition(condition["not"], record)
        return None if inner is None else not inner
    operator = condition.get("operator")
    value = _lookup(record, condition.get("field"))
    expected = condition.get("value")
    if operator == "empty":
        return is_blank(value)
    if operator == "notEmpty":
        return not is_blank(value)
    if operator == "equals":
        return _same(value, expected)
    if operator == "notEquals":
        return not _same(value, expected)
    if operator in ("in", "notIn"):
        options = expected if isinstance(expected, (list, tuple, set)) else [expected]
        found = any(_same(value, option) for option in options)
        return found if operator == "in" else not found
    if operator == "contains":
        if isinstance(value, (list, tuple, set)):
            return any(_same(item, expected) for item in value)
        return value is not None and str(expected).lower() in str(value).lower()
    return None


def _actions(options: Any, name: str) -> list[dict]:
    actions = options.get("actions") if isinstance(options, dict) else None
    return [a for a in actions or [] if isinstance(a, dict) and a.get("action") == name]


def is_visible(options: Any, record: dict) -> bool:
    """A hide action that holds hides the widget; with show actions it is
    visible only while one of them holds. Without actions it is visible."""
    for action in _actions(options, "hide"):
        if evaluate_condition(action.get("condition"), record) is True:
            return False
    shows = _actions(options, "show")
    if shows:
        return any(evaluate_condition(a.get("condition"), record) is not False for a in shows)
    return True


def is_required(static: Any, options: Any, record: dict) -> bool:
    if static:
        return True
    return any(evaluate_condition(a.get("condition"), record) is not False for a in _actions(options, "require"))


def _condition_fields(options: Any, actions: tuple[str, ...] = ("show", "hide", "require")) -> list[str]:
    """The fields the conditions of a widget's actions read."""
    found: list[str] = []

    def collect(condition: Any) -> None:
        if not isinstance(condition, dict):
            return
        for key in ("and", "or"):
            for inner in condition.get(key) or []:
                collect(inner)
        collect(condition.get("not"))
        field = _field_of(condition.get("field"))
        if field and field not in found:
            found.append(field)

    for name in actions:
        for action in _actions(options, name):
            collect(action.get("condition"))
    return found


def condition_fields(schema: Any) -> list[str]:
    """Every field the show / hide / require conditions of a section's widgets
    read. A condition may read a field of another section (the Work location is
    required unless the position is ADMIN); a check of one section then needs
    that field from the rest of the record."""
    found: list[str] = []
    for widget in _walk(schema):
        for field in _condition_fields(widget.get("widget-data-options")):
            if field not in found:
                found.append(field)
    return found


def came_from_another_system(record: dict) -> bool:
    """A file import (its source says so) or a DA Services push (it carries the
    record's reference in DA Services)."""
    from .validation_rules import is_interactive

    return not is_interactive(record) or not is_blank(record.get("upstream_reference"))


def hidden_fields(schema: Any, record: dict) -> list[str]:
    """Fields of a section that none of its visible widgets writes for this
    record: a widget hidden by its condition does not collect a value, so the
    record should not keep one (a specialisation once the position is no
    longer a development agent's)."""
    shown: set[str] = set()
    hidden: list[str] = []
    for fields, _label, _static, options, columns, _import_optional in _widgets(schema):
        if columns:
            continue
        # A record that does not carry the field a condition reads (a change of
        # another field only) says nothing about the widget: leave its value.
        if not all(name in record for name in _condition_fields(options, ("show", "hide"))) \
                or is_visible(options, record):
            shown.update(fields)
        else:
            hidden.extend(f for f in fields if f not in hidden)
    return [f for f in hidden if f not in shown]


def _title(key: str) -> str:
    return key.replace("_", " ").replace("-", " ").strip().capitalize()


def _widgets(schema: Any):
    """(fields, label, static_required, options, columns, optional on import)
    per input widget."""
    for widget in _walk(schema):
        if widget.get("widget-readonly"):
            continue
        columns = [c for c in widget.get("widget-data-columns") or [] if isinstance(c, dict) and c.get("column-key")]
        yield (
            _fields_of(widget.get("widget-data-path")),
            str(widget.get("widget-label") or "").strip(),
            widget.get("widget-required"),
            widget.get("widget-data-options"),
            columns,
            bool(widget.get("oan-optional-on-import")),
        )


def has_requirements(schema: Any) -> bool:
    """Whether any widget of the schema is, or can become, required."""
    for _fields, _label, static, options, columns, _import_optional in _widgets(schema):
        if static or _actions(options, "require"):
            return True
        if any(c.get("widget-required") or _actions(c.get("widget-data-options"), "require") for c in columns):
            return True
    return False


def problems(schema: Any, record: dict, *, absent_is_missing: bool) -> list[str]:
    """What a record leaves unfilled in a section, as readable phrases:
    "fill in Phone number", "add at least one Contacts row",
    "Contacts row 2: fill in Phone". Hidden widgets are skipped.
    absent_is_missing as in missing_labels."""
    fill: list[str] = []
    extra: list[str] = []
    imported = came_from_another_system(record)
    for fields, label, static, options, columns, import_optional in _widgets(schema):
        if not fields or not is_visible(options, record):
            continue
        required = is_required(static, options, record) and not (import_optional and imported)
        name = label or _title(fields[0])
        if columns:
            field = fields[0]
            if field not in record and not absent_is_missing:
                continue
            rows = [r for r in (record.get(field) or []) if isinstance(r, dict)]
            if required and not rows:
                extra.append(f"add at least one {name} row")
            for number, row in enumerate(rows, 1):
                missing = []
                for column in columns:
                    key = column["column-key"]
                    if not is_visible(column.get("widget-data-options"), row):
                        continue
                    if is_required(column.get("widget-required"), column.get("widget-data-options"), row) \
                            and is_blank(row.get(key)):
                        missing.append(str(column.get("column-label") or column.get("widget-label") or _title(key)))
                if missing:
                    extra.append(f"{name} row {number}: fill in " + ", ".join(missing))
            continue
        if not required:
            continue
        if any((f in record and is_blank(record.get(f))) or (f not in record and absent_is_missing) for f in fields):
            if name not in fill:
                fill.append(name)
    return (["fill in " + ", ".join(fill)] if fill else []) + extra


def _table(schema: Any) -> dict | None:
    """The table widget of a list section: the widget that carries the columns."""
    for widget in _walk(schema):
        if isinstance(widget.get("widget-data-columns"), list):
            return widget
    return None


def list_requires_row(schema: Any, parent: dict | None = None) -> bool:
    """Whether a list section must hold at least one row: its table widget is
    marked required, or carries a "require" action whose condition holds for
    the parent record (education records are required of a development agent,
    not of an administrator). Without the parent record only the plain flag
    counts. A list such as dependents may be left empty."""
    table = _table(schema)
    if not table:
        return False
    if table.get("widget-required"):
        return True
    if not parent:
        return False
    return any(
        evaluate_condition(a.get("condition"), parent) is True
        for a in _actions(table.get("widget-data-options"), "require")
    )


def row_problems(schema: Any, row: dict, *, absent_is_missing: bool) -> list[str]:
    """What one row of a list section leaves unfilled: "fill in Passout year".
    The row is the child record itself; the table's columns name its fields."""
    table = _table(schema)
    if not table:
        return []
    missing: list[str] = []
    for column in table.get("widget-data-columns") or []:
        if not isinstance(column, dict) or not column.get("column-key") or column.get("widget-readonly"):
            continue
        key = column["column-key"]
        options = column.get("widget-data-options")
        if not is_visible(options, row) or not is_required(column.get("widget-required"), options, row):
            continue
        if (key in row and is_blank(row.get(key))) or (key not in row and absent_is_missing):
            label = str(column.get("column-label") or column.get("widget-label") or _title(key))
            if label not in missing:
                missing.append(label)
    return ["fill in " + ", ".join(missing)] if missing else []


def describe(section_name: str, phrases: list[str]) -> str:
    return f"{section_name}: " + "; ".join(phrases)


def _section_title(schema: Any) -> str:
    """The section-title a staff member sees on the form, when the UI schema has one."""
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except ValueError:
            return ""
    title = str(schema.get("section-title") or "").strip() if isinstance(schema, dict) else ""
    return "" if "_" in title else title


def section_name_of(section: Any) -> str:
    """The section's title as shown on the form (its UI schema's section-title),
    else its description or mnemonic."""
    title = _section_title(getattr(section, "section_ui_schema", None))
    if title:
        return title
    text = str(getattr(section, "section_description", "") or getattr(section, "section_mnemonic", "") or "")
    return text.strip() or "Section"


_cache: dict[str, tuple[float, list[tuple[str, Any, bool]]]] = {}


def set_sections_for_tests(register_id: str, sections: list[tuple[str, Any, bool]] | None) -> None:
    if sections is None:
        _cache.pop(register_id, None)
    else:
        _cache[register_id] = (float("inf"), list(sections))


async def load_sections(register_id: str = DA_REGISTER_ID) -> list[tuple[str, Any, bool]]:
    """(name, ui schema, is_list) for every section of a register, from the DB."""
    hit = _cache.get(register_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    from openg2p_fastapi_common.context import get_async_session_maker
    from openg2p_registry_core.models import G2PRegisterSection
    from sqlalchemy import select

    async with get_async_session_maker()() as session:
        rows = (await session.execute(
            select(G2PRegisterSection).where(G2PRegisterSection.register_id == register_id)
            .order_by(G2PRegisterSection.section_weightage)
        )).scalars().all()
    sections = [(section_name_of(r), r.section_ui_schema, bool(r.is_list)) for r in rows]
    _cache[register_id] = (time.monotonic() + _CACHE_SECONDS, sections)
    return sections


def load_sections_sync(session: Any, register_id: str = DA_REGISTER_ID) -> list[tuple[str, Any, bool]]:
    """load_sections for the synchronous enrichers, which get a plain Session."""
    hit = _cache.get(register_id)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    from openg2p_registry_core.models import G2PRegisterSection
    from sqlalchemy import select

    rows = session.execute(
        select(G2PRegisterSection).where(G2PRegisterSection.register_id == register_id)
        .order_by(G2PRegisterSection.section_weightage)
    ).scalars().all()
    sections = [(section_name_of(r), r.section_ui_schema, bool(r.is_list)) for r in rows]
    _cache[register_id] = (time.monotonic() + _CACHE_SECONDS, sections)
    return sections


def incomplete_reason(record: dict, sections: list[tuple[str, Any, bool]]) -> str | None:
    """The reason "Required: <Section>: fill in <Field>; ..." for a whole record that
    leaves required, visible fields empty; None when it is complete."""
    found = []
    for name, schema, is_list in sections:
        if is_list:
            # A list section's rows are records of a child register (education
            # records, dependents). A file row or a push carries one education
            # in the DA record's own fields; where the record's position needs
            # an education record, those fields must be filled.
            if list_requires_row(schema, record):
                phrases = row_problems(schema, record, absent_is_missing=True)
                if phrases:
                    found.append(describe(name, phrases))
            continue
        phrases = problems(schema, record, absent_is_missing=True)
        if phrases:
            found.append(describe(name, phrases))
    return "Required: " + "; ".join(found) if found else None
