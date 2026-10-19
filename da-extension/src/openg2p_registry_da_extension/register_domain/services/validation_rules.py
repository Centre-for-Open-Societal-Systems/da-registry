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

# Fayda FIN: 12 digits.
FAYDA_FIN_PATTERN = r"^[0-9]{12}$"

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

# Required on the paths where a person fills in the form (agreed with the
# team, Oct 2026). Imports and syncs are format-checked only, so one bad cell
# does not reject an otherwise usable row.
REQUIRED_FIELDS = {
    "first_name": "Name",
    "middle_name": "Father Name",
    "gender": "Gender",
    "marital_status": "Marital Status",
    "birth_month_ec": "Month of Birth (EC)",
    "birth_year_ec": "Year of Birth (EC)",
    "mobile_number": "Phone Number",
    "email": "Email",
    "education_level": "Education Level",
    "specialisation": "Specialisation",
    "position": "Position",
    "foundational_id": "Fayda ID",
}

MIN_AGE_YEARS = 18

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
