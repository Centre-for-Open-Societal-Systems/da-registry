"""Region / Zone / Woreda codes of a DA, taken from its location chain.

DA Services scopes and filters DAs by code (names repeat: 23 Woreda names and
790 Kebele names occur more than once), so the codes are kept in their own
columns next to the names. A level's Master Data id is its type and code, e.g.
"woreda-ET040301", and the code is Master Data's OCHA P-code. Kebele ids do not
reliably carry their parents' codes, so each level is read from its own entry
in the chain, never from the Kebele id.
"""

import json

CODE_LEVELS = ("region", "zone", "woreda")


def code_of(level_value_id) -> str | None:
    """"woreda-ET040301" -> "ET040301"."""
    text = str(level_value_id or "").strip()
    if not text:
        return None
    return text.split("-", 1)[-1] or None


def geo_codes(chain) -> dict:
    """{"region_code", "zone_code", "woreda_code"} from a geo_code_hierarchy_json
    value (a dict, or its JSON text). Missing levels are None."""
    if isinstance(chain, str):
        try:
            chain = json.loads(chain)
        except ValueError:
            chain = None
    codes = {f"{level}_code": None for level in CODE_LEVELS}
    entries = chain.get("hierarchy") if isinstance(chain, dict) else None
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        level = str(entry.get("level_mnemonic") or entry.get("level") or "").strip().lower()
        if level in CODE_LEVELS:
            codes[f"{level}_code"] = code_of(entry.get("level_value_id"))
    return codes
