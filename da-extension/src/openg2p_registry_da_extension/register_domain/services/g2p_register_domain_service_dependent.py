"""Domain service of a DA's family members / dependents (child of DA).

A record is one row of the "Family members / dependents" table: the family
member's name, the relationship to the DA and, optionally, the date of birth.
"""

import logging
from datetime import date

from openg2p_registry_core.services import G2PRegisterDomainService

from .domain_validation_utils import parse_date, validation_error
from .validation_rules import NAME_MAX_LENGTH

_logger = logging.getLogger("g2p-register-domain-service")

REQUIRED = (("member_name", "Family member name"), ("relationship", "Relationship"))
_SKIP_ACTIONS = {"DELETE", "NO_CHANGE"}


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _check(record: dict) -> None:
    fields = REQUIRED if record.get("edit_action") == "ADD" else [f for f in REQUIRED if f[0] in record]
    missing = [label for field, label in fields if _is_blank(record.get(field))]
    if missing:
        validation_error("Required: Family members / dependents: fill in " + ", ".join(missing) + ".")
    name = record.get("member_name")
    if isinstance(name, str):
        record["member_name"] = " ".join(name.split())
        if len(record["member_name"]) > NAME_MAX_LENGTH * 3:
            validation_error("Family member name: the name is too long. Shorten it.")
    born = parse_date(record.get("date_of_birth"))
    if born is not None and born > date.today():
        validation_error("Date of birth: the date is in the future. Enter today or an earlier date.")


class G2PRegisterDomainServiceDependent(G2PRegisterDomainService):
    _KEYS = ("member_name", "relationship")

    async def validate_domain_attributes(self, records: list[dict]):
        for record in records:
            if record.get("edit_action") not in _SKIP_ACTIONS:
                _check(record)

    def _joined(self, payload: dict, extra: list[str] | None) -> str:
        parts = [str(item).strip() for item in (extra or []) if str(item).strip()]
        parts.extend(str(payload.get(key) or "").strip() for key in self._KEYS if str(payload.get(key) or "").strip())
        return " ".join(parts).strip()

    def construct_search_text(self, payload: dict, extra: list[str] = None) -> str:
        return self._joined(payload, extra)

    def construct_record_name(self, payload: dict, extra: list[str] = None) -> str:
        return self._joined(payload, extra)
