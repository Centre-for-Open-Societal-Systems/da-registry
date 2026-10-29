"""A DA submission cannot be saved empty or sent for approval incomplete.

The platform's intake service validates a section's records when they are
saved, but only the fields the request carries, and at finalize it validates
nothing: a form saved with its required fields left out (the staff UI omits
untouched fields) reaches the approvers as an empty record. This subclass
adds the two checks the DA registry needs, driven by the register metadata
(required_fields.py):

- save: a new record (edit_action ADD) of a web-intake submission must carry
  every required field of that section, so "Next" on an empty section answers
  "Required: ..." instead of "Saved";
- finalize: every section of the submission must have its required fields,
  so an incomplete submission never starts an approval.

Imports and DA Services pushes are not affected: they are format-checked only
(see validation_rules.is_interactive), and they do not go through the intake
form endpoints.

The service also refuses the direct approval of a submission
(direct_approval.py): a submission is approved only through its approval task.

Installed with install_da_intake_guard(): the instance goes to the front of
the platform's component registry, so G2PIntakeFormDataService.get_component()
(what the controllers call) resolves to it. No platform code is changed.
"""

from __future__ import annotations

import logging

from openg2p_registry_core.services.intake_form_data_service import G2PIntakeFormDataService

from .component_registration import register_ahead_of_platform
from .direct_approval import DirectApprovalClosed
from .domain_validation_utils import validation_error
from .required_fields import missing_labels, required_fields_in_schema
from .validation_rules import is_interactive

_logger = logging.getLogger("da-intake-guard")


class DAIntakeFormDataService(DirectApprovalClosed, G2PIntakeFormDataService):
    async def save_intake_form_submission_with_session(
        self, submission_id, section_id, section_payload, section_register_id, form_id, register_id,
        created_by, session, documents=None,
    ):
        section = await self._get_section_or_error(section_id, session)
        required = required_fields_in_schema(section.section_ui_schema)
        existing = await self._existing_record_ids(submission_id, section_register_id, session)
        missing: list[str] = []
        for record in self._records_for_validation(section_payload):
            if not isinstance(record, dict) or not is_interactive(record):
                continue
            # A record is new unless the submission already holds it, whatever
            # edit_action the client put on it: the staff UI sends UPDATE for a
            # section it believes it saved, even when nothing was stored.
            new = str(record.get("internal_record_id") or "") not in existing
            for label in missing_labels(required, record, absent_is_missing=new):
                if label not in missing:
                    missing.append(label)
        if missing:
            validation_error("Required: " + ", ".join(missing))
        return await super().save_intake_form_submission_with_session(
            submission_id, section_id, section_payload, section_register_id, form_id, register_id,
            created_by, session, documents=documents,
        )

    async def _existing_record_ids(self, submission_id, section_register_id, session) -> set[str]:
        """internal_record_ids the submission already stores for this register."""
        if not submission_id:
            return set()
        try:
            submission = await self._get_submission_or_error(submission_id, session)
            intake_class = await self._resolve_intake_form_class(section_register_id, session)
            rows = await self._get_intake_rows(intake_class, submission.submission_id, session)
        except Exception as exc:  # noqa: BLE001 - unknown submission: the platform decides below
            _logger.info("intake guard: no stored rows for submission %s (%s)", submission_id, exc)
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
        missing: list[str] = []
        for section in sections:
            required = required_fields_in_schema(section.section_ui_schema)
            if not required:
                continue
            payload = payloads.get(section.section_id)
            records = [r for r in (payload.records if payload else []) if isinstance(r, dict)]
            if section.is_list:
                # A list section needs one row; each row carries its own required fields.
                targets = records or [{}]
            else:
                targets = [records[0] if records else {}]
            for record in targets:
                if records and not is_interactive(record):
                    continue
                for label in missing_labels(required, record, absent_is_missing=True):
                    if label not in missing:
                        missing.append(label)
        if missing:
            validation_error("Cannot submit for approval. Required: " + ", ".join(missing))
        return await super().finalize_submission_with_session(
            submission_id, session, finalized_by, bearer_token=bearer_token, requester_sub=requester_sub,
        )


def install_da_intake_guard() -> DAIntakeFormDataService:
    """Register the DA intake service ahead of the platform's."""
    service = register_ahead_of_platform(DAIntakeFormDataService)
    _logger.info("DA intake guard installed: required fields checked on save and finalize; no direct approval")
    return service
