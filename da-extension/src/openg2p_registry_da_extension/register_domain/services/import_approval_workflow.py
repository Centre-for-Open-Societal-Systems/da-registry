"""Approval workflow for DA submissions that arrive without a signed-in user.

File import (CSV / XLSX) and partner ingestion (DA Services pushing a record)
create intake submissions from a celery worker. The platform then starts the
AWE approval workflow with the caller's bearer token, which a worker does not
have: the submission fails with AWE_BEARER_TOKEN_REQUIRED and the DA never
reaches the register.

This subclass of the platform's AWE integration service starts the workflow
for such a submission with a service token (awe_service_token.py), so each
imported DA gets the same two-stage approval tasks as a web-form submission
and is approved by the seeded approvers, stage by stage. Nothing is approved
automatically. If the service token cannot be obtained the finalisation fails
with a clear message, so the row shows up as failed in the import outcome /
exceptions list instead of silently staying PENDING.

Web intake (a staff user with a token) is untouched.

Registered ahead of the platform service in the component registry (see
component_registration.py); it applies in the staff API, the partner API and
the celery worker alike.
"""

import logging

from openg2p_registry_core.services.g2p_awe_integration_service import G2PAweIntegrationService
from sqlalchemy import text

from .awe_service_token import ServiceTokenUnavailable, get_service_token
from .component_registration import register_ahead_of_platform

_logger = logging.getLogger("da-import-approval")

DA_REGISTER_MNEMONIC = "DA"
UNATTENDED_SOURCES = {"PARTNER"}  # file import and partner ingestion


def is_unattended(submission, bearer_token) -> bool:
    """A submission no signed-in user is behind: no bearer token, and created
    by file import or partner ingestion."""
    source = str(getattr(submission, "submission_source", "") or "").strip().upper()
    return not (bearer_token or "").strip() and source in UNATTENDED_SOURCES


async def _is_da_register(session, register_id: str) -> bool:
    mnemonic = (
        await session.execute(
            text("SELECT register_mnemonic FROM g2p_register_definitions WHERE register_id = :rid"),
            {"rid": register_id},
        )
    ).scalar_one_or_none()
    return mnemonic == DA_REGISTER_MNEMONIC


class DAAweIntegrationService(G2PAweIntegrationService):
    async def start_intake_submission_workflow(self, session, submission, *args, **kwargs):
        if is_unattended(submission, kwargs.get("bearer_token")) and await _is_da_register(
            session, submission.register_id
        ):
            try:
                kwargs["bearer_token"] = await get_service_token()
            except ServiceTokenUnavailable as exc:
                _logger.error("DA submission %s: %s", submission.submission_id, exc)
                raise RuntimeError(f"DA approval could not be started: {exc}") from exc
            _logger.info(
                "DA submission %s (%s) sent for approval with the service token",
                submission.submission_id, getattr(submission, "submission_source", ""),
            )
        return await super().start_intake_submission_workflow(session, submission, *args, **kwargs)


def install_da_import_approval_workflow() -> DAAweIntegrationService:
    return register_ahead_of_platform(DAAweIntegrationService)
