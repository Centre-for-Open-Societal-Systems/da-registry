"""How far down the Work location goes, by position (decision of 18 Nov 2026;
the executive officer's level changed to the Zone on 27 Nov 2026).

A development agent works in one Kebele; a supervisor looks after a whole
Woreda and an executive officer a whole Zone; an administrator or a
communication officer works at no one place. The Work location's geo widget says so in the register
metadata (95_work_location.sql), under a key of OAN's own:

    "oan-location-depth": {
        "field": "<register_id>.position",
        "levels": {"SUPERVISOR": "woreda", "EXECUTIVE_OFFICER": "zone",
                   "ADMIN": "none", "COMMUNICATION_OFFICER": "none"},
        "default": "kebele"
    }

A level is the Master Data level mnemonic the location ends at; "none" means
the position has no Work location. A position not named takes "default", and
so does a record whose position is not known yet.

One rule, read everywhere:

- the form shows the levels down to the position's one and no Work location
  for "none" (ui/staff-ui/overrides/src/oan/widgets/GeoByPositionWidget.tsx);
- required_fields.py turns the key into the widget's hide and require
  actions, so the save, submit, import and push checks follow it;
- what goes deeper than the position's level is cut back to that level, and
  a position without a Work location keeps none: a file row or a push that
  fills those columns anyway is not refused for it, the extra values are
  left out (fit_record, and the enrichers);
- a location that stops above the position's level is refused with the level
  to choose.
"""

from __future__ import annotations

import json
from typing import Any

KEY = "oan-location-depth"
NONE = "none"
# Master Data levels from the top; a chain is cut by mnemonic, never by position
# in this list, so another country's levels work too.
LEVEL_ORDER = ("country", "region", "zone", "woreda", "kebele")


def _field_of(path: Any) -> str | None:
    if isinstance(path, str) and path.strip():
        return path.rsplit(".", 1)[-1].strip() or None
    return None


def rule_of(widget: Any) -> dict | None:
    rule = widget.get(KEY) if isinstance(widget, dict) else None
    if not isinstance(rule, dict) or not _field_of(rule.get("field")):
        return None
    return rule


def position_field(rule: dict) -> str:
    return _field_of(rule.get("field")) or "position"


def no_location_positions(rule: dict) -> list[str]:
    levels = rule.get("levels") if isinstance(rule.get("levels"), dict) else {}
    return sorted(str(p) for p, level in levels.items() if str(level).lower() == NONE)


def depth_for(rule: dict, record: dict) -> str:
    """The level the record's location ends at, or "none"."""
    levels = rule.get("levels") if isinstance(rule.get("levels"), dict) else {}
    position = record.get(position_field(rule))
    position = "" if position is None else str(position).strip()
    level = levels.get(position) if position else None
    return str(level or rule.get("default") or "kebele").strip().lower()


def synthesized_actions(rule: dict) -> list[dict]:
    """The key as show / hide / require actions: hidden for the positions
    without a Work location, required for every other one (a record whose
    position is not known yet included)."""
    field = str(rule.get("field"))
    none = no_location_positions(rule)
    if not none:
        return [{"action": "require", "condition": {"field": field, "operator": "notIn", "value": []}}]
    return [
        {"action": "hide", "condition": {"field": field, "operator": "in", "value": none}},
        {"action": "require", "condition": {"field": field, "operator": "notIn", "value": none}},
    ]


def _walk(node: Any):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def find_rule(sections: list) -> dict | None:
    """The rule of the register's geo widget, from (name, schema, is_list) sections."""
    for _name, schema, is_list in sections or []:
        if is_list:
            continue
        for node in _walk(schema):
            rule = rule_of(node)
            if rule:
                return rule
    return None


def _level(entry: Any) -> str:
    if not isinstance(entry, dict):
        return ""
    return str(entry.get("level_mnemonic") or entry.get("level") or "").strip().lower()


def chain_of(value: Any) -> dict | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, dict) and isinstance(value.get("hierarchy"), list):
        return value
    return None


def cut(chain: dict, level: str) -> dict | None:
    """The chain down to `level`, with its lowest id; None when the chain does
    not reach that level. A chain that ends there is returned as it is."""
    entries = list(chain.get("hierarchy") or [])
    for index, entry in enumerate(entries):
        if _level(entry) == level:
            if index == len(entries) - 1:
                return chain
            kept = entries[: index + 1]
            return {**chain, "hierarchy": kept, "lowest_level_value_id": kept[-1].get("level_value_id")}
    return None


def label(level: str) -> str:
    return level.replace("_", " ").title()


def levels_down_to(level: str) -> tuple[str, ...]:
    """The levels a file names, from the region down to `level`."""
    names = LEVEL_ORDER[1:]
    return names[: names.index(level) + 1] if level in names else names


def fit_record(record: dict, rule: dict, context: dict | None = None) -> str | None:
    """Fit a record's location to its position, in place.

    Deeper than the position's level: cut back to it. A position without a
    Work location: emptied. Above the position's level: the readable problem
    is returned ("choose the Kebele"), nothing is changed. `context` gives the
    position when the record does not carry it (a save of the location section
    alone)."""
    if "geo_lowest_level_value_id" not in record and "geo_code_hierarchy_json" not in record:
        return None
    field = position_field(rule)
    position = record.get(field)
    if position in (None, ""):
        position = (context or {}).get(field)
    if position in (None, ""):
        # Not known yet (the position is saved later): the submit check decides.
        return None
    depth = depth_for(rule, {field: position})
    if depth == NONE:
        record["geo_lowest_level_value_id"] = None
        record["geo_code_hierarchy_json"] = None
        return None
    chain = chain_of(record.get("geo_code_hierarchy_json"))
    if not chain or not record.get("geo_lowest_level_value_id"):
        return None
    fitted = cut(chain, depth)
    if fitted is None:
        return f"Work location: choose the {label(depth)}"
    if fitted is not chain:
        record["geo_code_hierarchy_json"] = fitted
        record["geo_lowest_level_value_id"] = fitted["lowest_level_value_id"]
    return None


def fitted_columns(row: dict, rule: dict) -> dict:
    """The columns to write so a stored DA row's location fits its position
    (see fit_record), with the names and codes kept next to it; {} when the
    row fits already. A location above the position's level is left for the
    form's checks."""
    from ...geo_codes import GEO_NAME_KEYS, geo_codes

    record = {key: row.get(key) for key in (position_field(rule), "geo_lowest_level_value_id", "geo_code_hierarchy_json")}
    before = record["geo_lowest_level_value_id"]
    if not before or fit_record(record, rule) or record["geo_lowest_level_value_id"] == before:
        return {}
    chain = chain_of(record["geo_code_hierarchy_json"])
    names = {
        _level(e): next((e.get(key) for key in GEO_NAME_KEYS if str(e.get(key) or "").strip()), None)
        for e in (chain or {}).get("hierarchy") or [] if isinstance(e, dict)
    }
    return {
        "geo_lowest_level_value_id": record["geo_lowest_level_value_id"],
        "geo_code_hierarchy_json": chain,
        **{f"{level}_name": names.get(level) for level in ("region", "zone", "woreda", "kebele")},
        **geo_codes(chain),
    }
