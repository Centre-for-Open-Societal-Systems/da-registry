"""Gregorian <-> Ethiopic (Amete Mihret) calendar conversion.

Pure arithmetic via Julian Day Number, deliberately dependency-free: the
extension only pins openg2p-fastapi-common and openg2p-g2pconnect-common-lib,
and a calendar conversion is not worth a third-party pin that then has to be
carried into every image stage.

The Ethiopian year has 13 months -- twelve of 30 days plus Pagumen, a 5 or 6
day epagomenal month. Month 13 is why an Ethiopic date cannot live in a
``date`` column: ``date(2015, 13, 5)`` raises ValueError, and Postgres rejects
it the same way. Ethiopic dates are therefore carried as ``YYYY-MM-DD``
strings, which sort correctly and round-trip exactly.
"""

from __future__ import annotations

import re
from datetime import date

# JDN of 1 Meskerem 1 in the Amete Mihret (Year of Mercy) reckoning, the era
# in civil use in Ethiopia.
_JD_EPOCH_OFFSET_AMETE_MIHRET = 1723856

_EC_PATTERN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

ETHIOPIC_MONTH_NAMES = (
    "Meskerem", "Tikimt", "Hidar", "Tahsas", "Tir", "Yekatit",
    "Megabit", "Miyazia", "Ginbot", "Sene", "Hamle", "Nehase", "Pagumen",
)


def _gregorian_to_jdn(year: int, month: int, day: int) -> int:
    a = (14 - month) // 12
    y = year + 4800 - a
    m = month + 12 * a - 3
    return day + (153 * m + 2) // 5 + 365 * y + y // 4 - y // 100 + y // 400 - 32045


def _jdn_to_gregorian(jdn: int) -> tuple[int, int, int]:
    a = jdn + 32044
    b = (4 * a + 3) // 146097
    c = a - 146097 * b // 4
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m = (5 * e + 2) // 153
    return (
        100 * b + d - 4800 + m // 10,
        m + 3 - 12 * (m // 10),
        e - (153 * m + 2) // 5 + 1,
    )


def _ethiopic_to_jdn(year: int, month: int, day: int) -> int:
    return (
        (_JD_EPOCH_OFFSET_AMETE_MIHRET + 365)
        + 365 * (year - 1)
        + year // 4
        + 30 * month
        + day
        - 31
    )


def _jdn_to_ethiopic(jdn: int) -> tuple[int, int, int]:
    r = (jdn - _JD_EPOCH_OFFSET_AMETE_MIHRET) % 1461
    n = (r % 365) + 365 * (r // 1460)
    return (
        4 * ((jdn - _JD_EPOCH_OFFSET_AMETE_MIHRET) // 1461) + r // 365 - r // 1460,
        n // 30 + 1,
        n % 30 + 1,
    )


def is_ethiopic_leap_year(year: int) -> bool:
    """Pagumen has 6 days in the year preceding a Gregorian leap year."""
    return year % 4 == 3


def ethiopic_month_length(year: int, month: int) -> int:
    if month == 13:
        return 6 if is_ethiopic_leap_year(year) else 5
    return 30


def is_valid_ethiopic_date(year: int, month: int, day: int) -> bool:
    if year < 1 or not 1 <= month <= 13 or day < 1:
        return False
    return day <= ethiopic_month_length(year, month)


def gregorian_to_ethiopic(value: date) -> tuple[int, int, int]:
    """Convert a Gregorian ``date`` to an (year, month, day) Ethiopic triple."""
    return _jdn_to_ethiopic(_gregorian_to_jdn(value.year, value.month, value.day))


def ethiopic_to_gregorian(year: int, month: int, day: int) -> date:
    """Convert an Ethiopic triple to a Gregorian ``date``.

    Raises ValueError on a triple that does not name a real Ethiopic day, so a
    typo'd Pagumen 6 in a common year fails loudly rather than silently sliding
    into the next month.
    """
    if not is_valid_ethiopic_date(year, month, day):
        raise ValueError(f"not a valid Ethiopic date: {year:04d}-{month:02d}-{day:02d}")
    return date(*_jdn_to_gregorian(_ethiopic_to_jdn(year, month, day)))


def format_ethiopic(year: int, month: int, day: int) -> str:
    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_ethiopic(value) -> tuple[int, int, int] | None:
    """Parse a stored ``YYYY-MM-DD`` Ethiopic string.

    Returns None for empty input and for anything not matching the shape, so
    callers can distinguish "absent" from "present but wrong" by validating
    separately. A ``date`` instance is accepted too: rows written before
    birth_date_ec became a string column still arrive that way.
    """
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return (value.year, value.month, value.day)
    if not isinstance(value, str):
        return None
    match = _EC_PATTERN.match(value.strip())
    if not match:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3)))


def gregorian_to_ethiopic_string(value: date) -> str:
    return format_ethiopic(*gregorian_to_ethiopic(value))
