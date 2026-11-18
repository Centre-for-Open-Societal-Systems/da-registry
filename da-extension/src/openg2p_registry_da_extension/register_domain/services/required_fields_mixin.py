"""Required-field checks for the DA intake service, from the register metadata.

widget-required (with the show / hide / require conditions of
widget-data-options, see required_fields.py) is the single source of truth.

- save ("Next"): a new record of a web-intake section must carry every
  required, visible field of that section. A partial update only has its blank
  fields refused. A list section whose table is marked required (education &
  professional records) is refused with no rows; one that is not (dependents)
  may stay empty.
- submit (finalize): every section of the submission is checked on the server
  for every channel - web, file import and partner push - so an incomplete
  submission never starts an approval.

Messages are readable and name the section, e.g.
"Cannot submit for approval. Required: DA contact details: fill in Mobile Number".
"""

from __future__ import annotations

import logging

from openg2p_registry_da_extension.register_domain.services.domain_validation_utils import validation_error
from openg2p_registry_da_extension.register_domain.services.required_fields import (
    DA_REGISTER_ID,
    condition_fields,
    describe,
    has_requirements,
    list_requires_row,
    load_sections,
    problems,
    row_problems,
    section_name_of,
)
from openg2p_registry_da_extension.register_domain.services import location_depth
from openg2p_registry_da_extension.register_domain.services.validation_rules import is_interactive

_logger = logging.getLogger("da-intake-guard")

EMPTY_LIST = "add at least one row"


def _add(found: dict[str, list[str]], name: str, phrases: list[str]) -> None:
    bucket = found.setdefault(name, [])
    for phrase in phrases:
        if phrase not in bucket:
            bucket.append(phrase)
    if not bucket:
        del found[name]


def _sentence(found: dict[str, list[str]]) -> str:
    return "Required: " + "; ".join(describe(name, phrases) for name, phrases in found.items())


class RequiredFieldsMixin:
    """Placed ahead of the platform intake service; see the module docstring."""

    async def save_intake_form_submission_with_session(
        self, submission_id, section_id, section_payload, section_register_id, form_id, register_id,
        created_by, session, documents=None,
    ):
        section = await self._get_section_or_error(section_id, session)
        schema = section.section_ui_schema
        if has_requirements(schema):
            existing = await self._existing_record_ids(submission_id, section_register_id, session)
            name = section_name_of(section)
            found: dict[str, list[str]] = {}
            is_list = bool(getattr(section, "is_list", False))
            records = [r for r in self._records_for_validation(section_payload) if isinstance(r, dict)]
            # A condition may read a field another section holds (Work location is
            # required unless the position is ADMIN): take it from the submission.
            wanted = [] if is_list else condition_fields(schema)
            parent = await self._parent_record(submission_id, session) if wanted else {}
            context = {field: parent[field] for field in wanted if parent.get(field) not in (None, "")}
            for record in records:
                if not is_interactive(record):
                    continue
                # A record is new unless the submission already holds it, whatever
                # edit_action the client put on it: the staff UI sends UPDATE for a
                # section it believes it saved, even when nothing was stored.
                new = str(record.get("internal_record_id") or "") not in existing
                if is_list:
                    if record.get("edit_action") != "DELETE":
                        _add(found, name, row_problems(schema, record, absent_is_missing=new))
                else:
                    seen = {**{k: v for k, v in context.items() if k not in record}, **record}
                    _add(found, name, problems(schema, seen, absent_is_missing=new))
            if is_list and list_requires_row(schema, await self._parent_record(submission_id, session)):
                kept = {str(r.get("internal_record_id")) for r in records if r.get("internal_record_id")} | existing
                deleted = {
                    str(r.get("internal_record_id")) for r in (section_payload or [])
                    if isinstance(r, dict) and r.get("edit_action") == "DELETE"
                }
                if not records and not (kept - deleted):
                    _add(found, name, [EMPTY_LIST])
            if found:
                validation_error(_sentence(found))
        result = await super().save_intake_form_submission_with_session(
            submission_id, section_id, section_payload, section_register_id, form_id, register_id,
            created_by, session, documents=documents,
        )
        if section_register_id == DA_REGISTER_ID and any(
            isinstance(r, dict) and "position" in r for r in self._records_for_validation(section_payload) or []
        ):
            await self._fit_stored_location(getattr(result, "submission_id", None) or submission_id, session)
        return result

    async def _fit_stored_location(self, submission_id, session) -> None:
        """A change of position on the form reaches the Work location already
        saved in the submission: emptied for a position that has none, cut back
        to the Woreda for a supervisor (location_depth.py). The form then shows
        it so, and the record that is approved, and that DA Services reads,
        carries it so."""
        if not submission_id:
            return
        rule = location_depth.find_rule(await load_sections(DA_REGISTER_ID))
        if not rule:
            return
        try:
            submission = await self._get_submission_or_error(submission_id, session)
            intake_class = await self._resolve_intake_form_class(DA_REGISTER_ID, session)
            rows = await self._get_intake_rows(intake_class, submission.submission_id, session)
        except Exception as exc:  # noqa: BLE001 - nothing stored yet
            _logger.warning("location fit: no DA record for submission %s (%s)", submission_id, exc)
            return
        changed = False
        for row in rows.values() if isinstance(rows, dict) else rows:
            stored = {key: getattr(row, key, None) for key in (
                location_depth.position_field(rule), "geo_lowest_level_value_id", "geo_code_hierarchy_json")}
            for key, value in location_depth.fitted_columns(stored, rule).items():
                if hasattr(row, key):
                    setattr(row, key, value)
                    changed = True
        if changed:
            await session.flush()

    async def _parent_record(self, submission_id, session) -> dict:
        """The DA record the submission holds so far, for a list section whose
        need for a row depends on it (the position decides whether an education
        record is required). Empty when nothing is stored yet; the submit check
        then decides."""
        if not submission_id:
            return {}
        try:
            submission = await self._get_submission_or_error(submission_id, session)
            intake_class = await self._resolve_intake_form_class(DA_REGISTER_ID, session)
            rows = await self._get_intake_rows(intake_class, submission.submission_id, session)
        except Exception as exc:  # noqa: BLE001 - nothing stored yet
            _logger.warning("intake guard: no DA record for submission %s (%s)", submission_id, exc)
            return {}
        for row in rows.values() if isinstance(rows, dict) else rows:
            if hasattr(row, "to_dict"):
                return dict(row.to_dict())
            return {key: value for key, value in vars(row).items() if not key.startswith("_")}
        return {}

    async def _existing_record_ids(self, submission_id, section_register_id, session) -> set[str]:
        """internal_record_ids the submission already stores for this register."""
        if not submission_id:
            return set()
        try:
            submission = await self._get_submission_or_error(submission_id, session)
            intake_class = await self._resolve_intake_form_class(section_register_id, session)
            rows = await self._get_intake_rows(intake_class, submission.submission_id, session)
        except Exception as exc:  # noqa: BLE001 - unknown submission: the platform decides below
            _logger.warning("intake guard: no stored rows for submission %s (%s)", submission_id, exc)
            return set()
        # The platform returns {internal_record_id: row}; accept a list of rows too.
        ids = rows.keys() if isinstance(rows, dict) else (getattr(r, "internal_record_id", None) for r in rows)
        return {str(i) for i in ids if i}

    async def finalize_submission_with_session(
        self, submission_id, session, finalized_by=None, bearer_token=None, requester_sub=None,
    ):
        submission = await self._get_submission_or_error(submission_id, session)
        sections = await self._get_form_sections(submission.form_id, session)
        payloads = {p.section_id: p for p in await self._build_section_payloads(submission, session)}
        found: dict[str, list[str]] = {}
        # The DA record as the sections of the submission hold it: what a list
        # section's need for a row, and "came from a file or DA Services", are
        # decided by.
        parent: dict = {}
        for section in sections:
            if getattr(section, "is_list", False):
                continue
            payload = payloads.get(section.section_id)
            for record in (payload.records if payload else [])[:1]:
                if isinstance(record, dict):
                    parent.update({k: v for k, v in record.items() if v is not None or k not in parent})
        for section in sections:
            schema = section.section_ui_schema
            if not has_requirements(schema):
                continue
            payload = payloads.get(section.section_id)
            records = [r for r in (payload.records if payload else []) if isinstance(r, dict)]
            name = section_name_of(section)
            if getattr(section, "is_list", False):
                # A list section that needs a row for this record must hold one;
                # each row carries its own required fields. A list that may stay
                # empty is skipped.
                if not records and list_requires_row(schema, parent):
                    _add(found, name, [EMPTY_LIST])
                for record in records:
                    _add(found, name, row_problems(schema, record, absent_is_missing=True))
                continue
            for record in [records[0] if records else {}]:
                # The whole record: a condition may read another section's field.
                _add(found, name, problems(schema, {**parent, **record}, absent_is_missing=True))
        if found:
            validation_error("Cannot submit for approval. " + _sentence(found))
        return await super().finalize_submission_with_session(
            submission_id, session, finalized_by, bearer_token=bearer_token, requester_sub=requester_sub,
        )
