"""Field rules for the DA register, applied on every path.

``widget-data-validation`` in the register metadata runs in the browser only.
CSV import and any partner ingestion never load that metadata, so the same
rules are restated here for the domain service. Keep the regexes identical to
the ones in the seed SQL.
"""

import re

# Latin plus Ethiopic (U+1200-U+137F), which covers Amharic and Afaan Oromo.
NAME_PATTERN = r"^[A-Za-zሀ-፿][A-Za-zሀ-፿\s'-]*$"
NAME_MAX_LENGTH = 100

# Fayda FAN (Fayda Alias Number, the 16-digit number printed on the card),
# the same number the farmer and livestock registries record. Decision of
# 28 Oct 2026 (Yash/Shikha): one Fayda format across the OAN registries.
FAYDA_FAN_PATTERN = r"^[0-9]{16}$"

# Ethiopian phone number: 9-digit national number, optionally prefixed with
# the trunk 0 or the +251 country code. Used for phone, Telegram and alternate.
PHONE_PATTERN = r"^(\+251|0)?[1-9][0-9]{8}$"

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"

NAME_FIELD_LABELS = {
    "first_name": "Name",
    "middle_name": "Father Name",
    "last_name": "Grandfather Name",
}
NAME_FIELDS = tuple(NAME_FIELD_LABELS)

PHONE_FIELD_LABELS = {
    "mobile_number": "Phone Number",
    "telegram_number": "Telegram Number",
    "alternate_number": "Alternate Number",
}

# Required fields are not listed here: widget-required in the register metadata
# is the single source (register_domain/services/required_fields.py).


INTERACTIVE_SOURCES = {"WEB_INTAKE"}

_COMPILED: dict[str, re.Pattern] = {}


def _compiled(pattern: str) -> re.Pattern:
    if pattern not in _COMPILED:
        _COMPILED[pattern] = re.compile(pattern)
    return _COMPILED[pattern]


def matches(pattern: str, value) -> bool:
    """True when value satisfies pattern. Blank passes: emptiness is a
    required-check concern, not a format one."""
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    return bool(_compiled(pattern).match(text))


def is_interactive(record: dict) -> bool:
    """Whether this record came from someone filling in the web intake form.
    An absent source is treated as interactive so a missing value fails closed."""
    source = str(record.get("source") or "").strip().upper()
    return not source or source in INTERACTIVE_SOURCES
