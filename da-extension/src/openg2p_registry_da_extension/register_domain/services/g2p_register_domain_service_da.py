import json
import logging
from datetime import date

from openg2p_registry_core.services import G2PRegisterDomainService
from sqlalchemy import text

from .choice_check import validate_choices
from .domain_validation_utils import as_int, parse_date, validation_error
from .ethiopian_calendar import gregorian_to_ethiopic
from .fayda_uniqueness import duplicate_message, find_fayda_owner
from . import location_depth, position_rights
from .required_fields import DA_REGISTER_ID, describe, hidden_fields, is_blank, load_sections, problems
from ...geo_codes import GEO_NAME_KEYS, geo_codes
from .validation_rules import (
    EMAIL_PATTERN,
    FAYDA_FAN_PATTERN,
    NAME_FIELD_LABELS,
    NAME_FIELDS,
    NAME_MAX_LENGTH,
    NAME_PATTERN,
    PHONE_FIELD_LABELS,
    PHONE_PATTERN,
    is_interactive,
    matches,
)

_logger = logging.getLogger("g2p-register-domain-service")

# The earliest year of birth the form accepts, in the Ethiopian calendar. The
# date of birth widget states the same limit as its minDate, 1 Meskerem 1920
# (12 September 1927).
MIN_BIRTH_YEAR_EC = 1920

# The same limit as the Home address box on the form (96_home_address.sql).
HOME_ADDRESS_MAX = 100


class G2PRegisterDomainServiceDA(G2PRegisterDomainService):
    """Domain rules for the DA register.

    Looked up by the platform through G2PRegisterDomainFactory as
    G2PRegisterDomainService<register mnemonic>, so the register mnemonic
    must be "DA".
    """

    async def validate_domain_attributes(self, records: list[dict]):
        sections = await load_sections(DA_REGISTER_ID) if records else []
        for record in records:
            self._normalise_source(record)
            self._validate_names(record)
            self._validate_fayda_fan(record)
            self._validate_phones(record)
            self._validate_email(record)
            self._validate_home_address(record)
            self._derive_birth_ec(record)
            self._validate_birth_ec(record)
            self._validate_joined_date(record)
            self._validate_passout_year(record)
            context = await self._condition_context(record, sections)
            self._clear_hidden_fields(record, sections, context)
            self._fit_location(record, sections, context)
            await position_rights.check(record, sections)
            self._validate_required(record, sections, context)
            await self._validate_reports_to(record)
            await validate_choices(record, sections)
            await self._check_fayda_unique(record)
            await self._sync_flattened_geo_names(record)

    # ------------------------------------------------------------ validation --
    @staticmethod
    def _normalise_source(record: dict) -> None:
        """Drop a blank source so an insert takes the column default
        (WEB_INTAKE) and an update leaves the stored value alone."""
        if "source" in record and not str(record.get("source") or "").strip():
            record.pop("source")

    @staticmethod
    def _validate_names(record: dict) -> None:
        for field in NAME_FIELDS:
            # An absent key is a partial update of other fields, not a blank.
            if field not in record:
                continue
            value = record.get(field)
            text = "" if value is None else str(value).strip()
            if not text:
                continue
            label = NAME_FIELD_LABELS.get(field, field)
            if len(text) > NAME_MAX_LENGTH:
                validation_error(f"{label}: too long. Enter {NAME_MAX_LENGTH} characters or fewer.")
            if not matches(NAME_PATTERN, text):
                validation_error(
                    f"{label}: use letters (Latin or Ethiopic), "
                    "spaces, hyphens and apostrophes only."
                )
            record[field] = text

    @staticmethod
    def _validate_fayda_fan(record: dict) -> None:
        if "foundational_id" not in record:
            return
        value = record.get("foundational_id")
        text = "" if value is None else str(value).strip().replace(" ", "").replace("-", "")
        if not text:
            record["foundational_id"] = None
            return
        if not matches(FAYDA_FAN_PATTERN, text):
            validation_error("Fayda ID (FAN): enter exactly 16 digits.")
        record["foundational_id"] = text

    @staticmethod
    def _validate_phones(record: dict) -> None:
        for field, label in PHONE_FIELD_LABELS.items():
            if field not in record:
                continue
            value = record.get(field)
            text = "" if value is None else str(value).strip().replace(" ", "").replace("-", "")
            if not text:
                record[field] = None
                continue
            if not matches(PHONE_PATTERN, text):
                validation_error(f"{label}: enter an Ethiopian phone number, for example 0911234567.")
            record[field] = text

    @staticmethod
    def _validate_home_address(record: dict) -> None:
        """Where the DA lives: optional, one line, up to HOME_ADDRESS_MAX
        characters. The form's text box states the same limit. A line break is
        refused, not removed: a change request stores what was sent, so a
        value tidied here would still reach the register as it came."""
        if "address_line_1" not in record:
            return
        value = record.get("address_line_1")
        text = "" if value is None else str(value).strip()
        if not text:
            record["address_line_1"] = None
            return
        if "\n" in text or "\r" in text:
            validation_error("Home address: write it on one line, without line breaks.")
        if len(text) > HOME_ADDRESS_MAX:
            validation_error(f"Home address: use {HOME_ADDRESS_MAX} characters or fewer (this one has {len(text)}).")
        record["address_line_1"] = text

    @staticmethod
    def _validate_email(record: dict) -> None:
        if "email" not in record:
            return
        value = record.get("email")
        text = "" if value is None else str(value).strip()
        if not text:
            record["email"] = None
            return
        if not matches(EMAIL_PATTERN, text):
            validation_error("Email: enter a valid email address, for example name@example.org.")
        record["email"] = text.lower()

    @staticmethod
    def _derive_birth_ec(record: dict) -> None:
        """The form takes one date of birth on the Ethiopian calendar picker;
        the stored value is the Gregorian birth_date. The month and year of
        birth in the Ethiopian calendar follow from it, so the DCI output,
        reports and month-and-year imports read the same two columns."""
        if "birth_date" not in record:
            return
        raw = record.get("birth_date")
        if raw in (None, ""):
            record["birth_date"] = None
            return
        born = parse_date(raw)
        if born is None:
            validation_error("Date of birth: enter a valid date.")
        if born > date.today():
            validation_error("Date of birth: the date is in the future. Enter a date that has passed.")
        year, month, _ = gregorian_to_ethiopic(born)
        if year < MIN_BIRTH_YEAR_EC:
            validation_error(
                f"Date of birth: enter a date in {MIN_BIRTH_YEAR_EC} of the Ethiopian calendar or later."
            )
        record["birth_date"] = born.isoformat()
        record["birth_month_ec"] = month
        record["birth_year_ec"] = year

    @staticmethod
    def _validate_birth_ec(record: dict) -> None:
        """Month / Year of Birth in the Ethiopian calendar: a real month, a
        4-digit year of 1920 or later (the limit the form states), not in the future. No
        minimum age: the FSD sets none (decision of 28 Oct 2026)."""
        if "birth_month_ec" not in record and "birth_year_ec" not in record:
            return
        month = as_int(record.get("birth_month_ec")) if "birth_month_ec" in record else None
        year = as_int(record.get("birth_year_ec")) if "birth_year_ec" in record else None
        if "birth_month_ec" in record:
            if record.get("birth_month_ec") not in (None, "") and month is None:
                validation_error("Month of birth (Ethiopian calendar): enter a number from 1 to 13.")
            if month is not None and not 1 <= month <= 13:
                validation_error("Month of birth (Ethiopian calendar): enter a number from 1 to 13.")
            record["birth_month_ec"] = month
        if "birth_year_ec" in record:
            if record.get("birth_year_ec") not in (None, "") and year is None:
                validation_error("Year of birth (Ethiopian calendar): enter a 4-digit year.")
            record["birth_year_ec"] = year
        if year is None:
            return
        today_y, today_m, _ = gregorian_to_ethiopic(date.today())
        if year < MIN_BIRTH_YEAR_EC:
            validation_error(f"Year of birth (Ethiopian calendar): enter {MIN_BIRTH_YEAR_EC} or later.")
        # Months on the 13-month Ethiopian year; an unknown month counts as the
        # first one so a current-year birth is not refused as "future".
        if (today_y * 13 + today_m) - (year * 13 + (month or 1)) < 0:
            validation_error("Month and year of birth (Ethiopian calendar): the date is in the future. Enter a date that has passed.")

    @staticmethod
    def _validate_joined_date(record: dict) -> None:
        joined = parse_date(record.get("joined_date"))
        if joined is not None and joined > date.today():
            validation_error("Joining date: the date is in the future. Enter today or an earlier date.")

    @staticmethod
    def _validate_passout_year(record: dict) -> None:
        from .g2p_register_domain_service_qualification import check_passout_year

        check_passout_year(record)

    @staticmethod
    def _clear_hidden_fields(record: dict, sections: list, context: dict | None = None) -> None:
        """A field the form hides for this record keeps no value: the
        specialisation of someone who is not a development agent, the person
        an administrator reports to, the Work location of an administrator or
        a communication officer. The form can still send what was typed
        before the position was changed. `context` gives the stored values the
        conditions read and the record does not carry (the position, on a save
        of the Work location alone)."""
        seen = {**{k: v for k, v in (context or {}).items() if k not in record and not is_blank(v)}, **record}
        for _name, schema, is_list in sections:
            if is_list:
                continue
            for field in hidden_fields(schema, seen):
                if field in record and not is_blank(record.get(field)):
                    record[field] = None

    @staticmethod
    def _fit_location(record: dict, sections: list, context: dict | None = None) -> None:
        """The Work location goes down to the position's level and no further
        (location_depth.py): a Kebele chosen for a supervisor is left out and
        the Woreda kept; a location that stops above the position's level is
        refused with the level to choose."""
        rule = location_depth.find_rule(sections)
        if not rule:
            return
        problem = location_depth.fit_record(record, rule, context)
        if problem:
            validation_error(problem)

    @staticmethod
    async def _validate_reports_to(record: dict) -> None:
        """"Reports to" is the DA-ID of a person in the register: an active
        record, and not the person's own. The ID must be written as the
        register has it: a change request stores what was sent, so an ID tidied
        here (case, spaces) would still reach the register as it came."""
        if "reports_to" not in record:
            return
        value = "" if record.get("reports_to") is None else str(record.get("reports_to"))
        if not value.strip():
            record["reports_to"] = None
            return
        from openg2p_fastapi_common.context import dbengine

        async with dbengine.get().connect() as conn:
            row = (
                await conn.execute(
                    text(
                        'SELECT "internal_record_id", "record_status" FROM "public"."g2p_register_das" '
                        'WHERE "functional_record_id" = :id ORDER BY ("record_status" = \'ACTIVE\') DESC LIMIT 1'
                    ),
                    {"id": value},
                )
            ).first()
        if row is None:
            validation_error(
                f"Reports to: no one in the register has the ID {value}. Choose the person from the list."
            )
        if str(row[1]) != "ACTIVE":
            validation_error(f"Reports to: {value} is no longer active in the register. Choose another person.")
        if str(row[0]) == str(record.get("internal_record_id") or ""):
            validation_error("Reports to: a person cannot report to themselves. Choose another person.")

    @staticmethod
    async def _condition_context(record: dict, sections: list) -> dict:
        """The stored values of the fields the sections' conditions read and the
        record does not carry: a change of the Work location alone does not
        carry the position its rule depends on. Read from the register record
        a change request is for, else from the record (register, then intake)
        with the record's id. Empty when there is nothing to read."""
        from .required_fields import condition_fields

        wanted = sorted({
            field for _name, schema, is_list in sections if not is_list
            for field in condition_fields(schema)
            if field not in record and field.replace("_", "").isalnum()
        })
        if not wanted:
            return {}
        from .position_rights import _change_target

        target = _change_target.get() or str(record.get("internal_record_id") or "")
        if not target:
            return {}
        from openg2p_fastapi_common.context import dbengine

        columns = ", ".join(f'"{field}"' for field in wanted)
        async with dbengine.get().connect() as conn:
            for table, order in (("g2p_register_das", ""), ("g2p_intake_form_das", ' ORDER BY "created_at" DESC')):
                row = (
                    await conn.execute(
                        text(f'SELECT {columns} FROM "public"."{table}" WHERE "internal_record_id" = :id{order} LIMIT 1'),
                        {"id": target},
                    )
                ).mappings().first()
                if row:
                    return dict(row)
        return {}

    @staticmethod
    def _validate_required(record: dict, sections: list, context: dict | None = None) -> None:
        """Required fields (widget-required in the register metadata, with its
        show / hide / require conditions), checked only when a person fills in
        the form. Only keys present in the record are checked here: the intake
        form saves one section at a time, and a change request carries only
        what changed. Absent keys are the intake guard's job
        (required_fields_mixin.py) on save and finalize; imports and partner
        pushes are checked whole by their enrichers."""
        if not is_interactive(record):
            return
        found = []
        for name, schema, is_list in sections:
            if is_list:
                continue  # rows of a child register, checked by that register's service
            # Stored values only feed the conditions; an empty one says nothing
            # and must not read as a field the record blanked.
            seen = {**{k: v for k, v in (context or {}).items() if k not in record and not is_blank(v)}, **record}
            phrases = problems(schema, seen, absent_is_missing=False)
            if phrases:
                found.append(describe(name, phrases))
        if found:
            validation_error("Required: " + "; ".join(found))

    # ------------------------------------------------------------------ geo --
    @staticmethod
    async def _check_fayda_unique(record: dict) -> None:
        """One DA per Fayda ID: refuse a Fayda ID another DA or another live
        submission already holds (see fayda_uniqueness)."""
        fayda_id = record.get("foundational_id")
        if not fayda_id:
            return
        registered, other = await find_fayda_owner(fayda_id, str(record.get("internal_record_id") or ""))
        message = duplicate_message(fayda_id, registered, other)
        if message:
            validation_error(message)

    async def _sync_flattened_geo_names(self, record: dict) -> None:
        """Flatten geo_code_hierarchy_json into region/zone/woreda/kebele_name
        so the list view and filters can use plain columns."""
        if "geo_lowest_level_value_id" not in record:
            return
        level_value_id = record.get("geo_lowest_level_value_id")
        levels = {"region": None, "zone": None, "woreda": None, "kebele": None}
        level_aliases = {
            "region": "region", "zone": "zone", "district": "zone",
            "woreda": "woreda", "ward": "woreda", "kebele": "kebele", "village": "kebele",
        }
        if level_value_id:
            from openg2p_registry_core.services import G2PGeoHierarchyService

            try:
                service = G2PGeoHierarchyService.get_component() or G2PGeoHierarchyService()
                hierarchy = await service.get_geo_hierarchy(level_value_id)
            except Exception as error:  # noqa: BLE001
                _logger.warning(f"Geo lookup for {level_value_id} failed, keeping stored names: {error}")
                if record.get("geo_code_hierarchy_json"):
                    record.update(geo_codes(record["geo_code_hierarchy_json"]))
                return
            if not (hierarchy or {}).get("hierarchy"):
                # Lookup failed (e.g. master data not reachable from this
                # worker): keep whatever names the record already carries, and
                # take the codes from the chain the record was saved with.
                if record.get("geo_code_hierarchy_json"):
                    record.update(geo_codes(record["geo_code_hierarchy_json"]))
                return
            for entry in hierarchy["hierarchy"]:
                mnemonic = (entry.get("level_mnemonic") or "").strip().lower()
                target = level_aliases.get(mnemonic)
                if target:
                    levels[target] = self._geo_display_name(entry)
        record["region_name"] = levels["region"]
        record["zone_name"] = levels["zone"]
        record["woreda_name"] = levels["woreda"]
        record["kebele_name"] = levels["kebele"]
        record.update(geo_codes(hierarchy if level_value_id else None))

    # ------------------------------------------------ location after a change --
    FLAT_GEO_COLUMNS = (
        "region_name", "zone_name", "woreda_name", "kebele_name",
        "region_code", "zone_code", "woreda_code", "kebele_code",
    )

    async def post_approve(self, change_request, session):
        """A change request stores only what the form sent: the Kebele id and
        its chain. The names and codes kept next to them (the Woreda and Kebele
        on the list, the codes DA Services scopes and filters by) are derived
        when a record is saved through the form, and a change request applies
        its payload as it is, so after a location change they still described
        the old place. Derive them again from the record once the change is in
        the register."""
        await super().post_approve(change_request, session)
        # A change of position can leave the Work location hidden (emptied) or
        # deeper than the new position's level (cut back): both before the names
        # and codes next to the location are derived again.
        await self._clear_hidden_after_change(change_request.internal_record_id, session)
        await self._fit_location_after_change(change_request.internal_record_id, session)
        await self._refresh_flattened_geo(change_request.internal_record_id, session)

    async def _fit_location_after_change(self, internal_record_id: str, session) -> None:
        """A change request applies its payload as it is: a development agent
        made a supervisor keeps the Kebele they had. Cut the location back to
        the new position's level (see _fit_location). A location above the
        position's level is left for the next edit to complete."""
        rule = location_depth.find_rule(await load_sections(DA_REGISTER_ID))
        if not rule:
            return
        row = (
            await session.execute(
                text(
                    'SELECT "position", "geo_lowest_level_value_id", "geo_code_hierarchy_json" '
                    'FROM "public"."g2p_register_das" WHERE "internal_record_id" = :id'
                ),
                {"id": internal_record_id},
            )
        ).mappings().first()
        if not row or not row["geo_lowest_level_value_id"]:
            return
        record = dict(row)
        before = record["geo_lowest_level_value_id"]
        if location_depth.fit_record(record, rule) or record["geo_lowest_level_value_id"] == before:
            return
        chain = record["geo_code_hierarchy_json"]
        await session.execute(
            text(
                'UPDATE "public"."g2p_register_das" SET "geo_lowest_level_value_id" = :lowest, '
                '"geo_code_hierarchy_json" = CAST(:chain AS jsonb) WHERE "internal_record_id" = :id'
            ),
            {"lowest": record["geo_lowest_level_value_id"],
             "chain": None if chain is None else json.dumps(chain), "id": internal_record_id},
        )

    async def _clear_hidden_after_change(self, internal_record_id: str, session) -> None:
        """A change request applies its payload as it is, so a field the form
        hides for the record's new position (see _clear_hidden_fields) is
        emptied once the change is in the register."""
        row = (
            await session.execute(
                text('SELECT * FROM "public"."g2p_register_das" WHERE "internal_record_id" = :id'),
                {"id": internal_record_id},
            )
        ).mappings().first()
        if not row:
            return
        record = dict(row)
        stale = [
            field
            for _name, schema, is_list in await load_sections(DA_REGISTER_ID)
            if not is_list
            for field in hidden_fields(schema, record)
            if field in record and not is_blank(record[field]) and field.replace("_", "").isalnum()
        ]
        if not stale:
            return
        assignments = ", ".join(f'"{field}" = NULL' for field in dict.fromkeys(stale))
        await session.execute(
            text(f'UPDATE "public"."g2p_register_das" SET {assignments} WHERE "internal_record_id" = :id'),
            {"id": internal_record_id},
        )

    async def _refresh_flattened_geo(self, internal_record_id: str, session) -> None:
        columns = ", ".join(f'"{name}"' for name in self.FLAT_GEO_COLUMNS)
        row = (
            await session.execute(
                text(
                    f'SELECT "geo_lowest_level_value_id", "geo_code_hierarchy_json", {columns} '
                    'FROM "public"."g2p_register_das" WHERE "internal_record_id" = :id'
                ),
                {"id": internal_record_id},
            )
        ).mappings().first()
        if not row:
            return
        if not row["geo_lowest_level_value_id"]:
            # No Work location (emptied for a position that has none): no names
            # or codes of a place either.
            stale = [name for name in self.FLAT_GEO_COLUMNS if row[name] is not None]
            if stale:
                await session.execute(
                    text(
                        'UPDATE "public"."g2p_register_das" SET '
                        + ", ".join(f'"{name}" = NULL' for name in stale)
                        + ' WHERE "internal_record_id" = :id'
                    ),
                    {"id": internal_record_id},
                )
            return
        record = {
            "geo_lowest_level_value_id": row["geo_lowest_level_value_id"],
            "geo_code_hierarchy_json": row["geo_code_hierarchy_json"],
        }
        await self._sync_flattened_geo_names(record)
        # Master Data not reachable: the names of the chain the record carries.
        for name, value in self._names_of_chain(row["geo_code_hierarchy_json"]).items():
            record.setdefault(name, value)
        changed = {
            name: record.get(name) for name in self.FLAT_GEO_COLUMNS
            if name in record and record.get(name) != row[name]
        }
        if not changed:
            return
        assignments = ", ".join(f'"{name}" = :{name}' for name in changed)
        await session.execute(
            text(f'UPDATE "public"."g2p_register_das" SET {assignments} WHERE "internal_record_id" = :id'),
            {**changed, "id": internal_record_id},
        )

    @classmethod
    def _names_of_chain(cls, chain) -> dict:
        """{"region_name": ..} from a geo_code_hierarchy_json value (dict or JSON text)."""
        if isinstance(chain, str):
            try:
                chain = json.loads(chain)
            except ValueError:
                chain = None
        names = {}
        for entry in (chain.get("hierarchy") if isinstance(chain, dict) else None) or []:
            level = str((entry or {}).get("level_mnemonic") or (entry or {}).get("level") or "").strip().lower()
            if level in ("region", "zone", "woreda", "kebele"):
                names[f"{level}_name"] = cls._geo_display_name(entry)
        return names

    @staticmethod
    def _geo_display_name(entry: dict) -> str | None:
        """The place's name as Master Data spells it. The record page shows that
        spelling, so the list must too: title-casing it made "Bure (OR)" read
        "Bure (Or)" on the list and "Dubti town" read "Dubti Town"."""
        for key in GEO_NAME_KEYS:
            value = str(entry.get(key) or "").strip()
            if value:
                return value
        return None

    # --------------------------------------------------- search / record name --
    def construct_search_text(self, payload: dict, extra: list[str] = None) -> str:
        keys = [
            "functional_record_id", "foundational_id",
            "first_name", "middle_name", "last_name",
            "mobile_number", "telegram_number", "alternate_number", "email",
            "education_level", "specialisation", "position",
            "region_name", "zone_name", "woreda_name", "kebele_name",
        ]
        parts = []
        if extra:
            parts.extend(str(v).strip() for v in extra if str(v).strip())
        parts.extend(
            str(payload.get(k) or "").strip() for k in keys if str(payload.get(k) or "").strip()
        )
        return " ".join(parts).strip()

    def construct_record_name(self, payload: dict, extra: list[str] = None) -> str:
        keys = ["first_name", "middle_name", "last_name"]
        parts = []
        if extra:
            parts.extend(str(v).strip() for v in extra if str(v).strip())
        parts.extend(
            str(payload.get(k) or "").strip() for k in keys if str(payload.get(k) or "").strip()
        )
        return " ".join(parts).strip()
