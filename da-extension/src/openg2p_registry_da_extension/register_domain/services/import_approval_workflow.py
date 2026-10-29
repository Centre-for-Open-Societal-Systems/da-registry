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
exceptions list instead of silently staying PENDING. The same holds when the
platform would return without opening a request (approval switched off in the
process, or no approval policy for the form): that is refused too, with the
reason, so no submission waits as Pending with no task for anyone.

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
NOT_STARTED = "The approval could not be started: "
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
        if not (is_unattended(submission, kwargs.get("bearer_token")) and await _is_da_register(
            session, submission.register_id
        )):
            return await super().start_intake_submission_workflow(session, submission, *args, **kwargs)
        # The platform returns without opening a request when approval is switched
        # off in the process or the form has no approval policy, and the
        # submission would then wait as "Pending" with no task for anyone. Refuse
        # instead, so the row shows as failed with the reason and can be retried.
        if not self._awe_enabled():
            _logger.error("DA submission %s: approval is switched off in this process", submission.submission_id)
            _logger.error("Set the worker's AWE_ENABLED, AWE_BASE_URL and callback settings (REGISTRY_CELERY_WORKERS_ prefix)")
            raise RuntimeError(NOT_STARTED + "approval is switched off for imports. Ask an administrator to check the approval service settings.")
        try:
            kwargs["bearer_token"] = await get_service_token()
        except ServiceTokenUnavailable as exc:
            _logger.error("DA submission %s: %s", submission.submission_id, exc)
            raise RuntimeError(f"{NOT_STARTED}{exc}") from exc
        _logger.info(
            "DA submission %s (%s) sent for approval with the service token",
            submission.submission_id, getattr(submission, "submission_source", ""),
        )
        result = await super().start_intake_submission_workflow(session, submission, *args, **kwargs)
        if not getattr(submission, "awe_request_id", None):
            _logger.error("DA submission %s: no approval request was opened", submission.submission_id)
            raise RuntimeError(NOT_STARTED + "no approval request was opened. Ask an administrator to check that the Development agent registration form has an approval policy.")
        return result


def install_da_import_approval_workflow() -> DAAweIntegrationService:
    return register_ahead_of_platform(DAAweIntegrationService)
