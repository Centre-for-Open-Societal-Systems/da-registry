"""Approval of DA submissions that arrive without a signed-in user.

File import (CSV / XLSX) and partner ingestion (DA Services pushing a record)
create intake submissions from a celery worker. The platform then starts the
AWE approval workflow with the caller's bearer token, which a worker does not
have: the submission fails with AWE_BEARER_TOKEN_REQUIRED and the DA never
reaches the register.

Default (DA_AUTO_APPROVE_IMPORTS=false, decision of 23 Oct 2026, Faiz and
Shikha: imports are approved manually like every other record): the workflow
is started with a service token (awe_service_token.py), so each imported DA
gets the same approval tasks as a web-form submission and is approved by the
seeded approvers, stage by stage. If the service token cannot be obtained the
finalisation fails with a clear message, so the row shows up as failed in the
import outcome / exceptions list instead of silently staying PENDING.

DA_AUTO_APPROVE_IMPORTS=true (the earlier behaviour, kept for a one-time
back-end load): the AWE workflow is skipped and the submission is approved
straight after it is finalised, unless its Fayda ID is already registered or
already in another live submission. Those stay PENDING with the reason in
`remarks`, for someone to resolve.

Web intake (a staff user with a token) is untouched in both modes.

Installed by wrapping the platform service's methods, the same way as the
record-image fix next to it; it applies to whichever service instance the
process registers, in the staff API, the partner API and the celery worker
alike.
"""

import functools
import logging
import os

from sqlalchemy import text

from .awe_service_token import ServiceTokenUnavailable, get_service_token

_logger = logging.getLogger("da-auto-approve")

DA_REGISTER_MNEMONIC = "DA"
AUTO_APPROVE_SOURCES = {"PARTNER"}  # file import and partner ingestion
AUTO_APPROVED_BY = "system (auto-approved import)"
_INSTALLED_MARKER = "_da_auto_approves_imports"


def auto_approve_enabled() -> bool:
    return os.environ.get("DA_AUTO_APPROVE_IMPORTS", "false").strip().lower() in ("1", "true", "yes", "on")


def is_unattended(submission, bearer_token) -> bool:
    """A submission no signed-in user is behind: no bearer token, and created
    by file import or partner ingestion."""
    source = str(getattr(submission, "submission_source", "") or "").strip().upper()
    return not (bearer_token or "").strip() and source in AUTO_APPROVE_SOURCES


def duplicate_reason(fayda_id: str, registered_da_id: str | None, other_reference: str | None) -> str | None:
    if registered_da_id:
        return f"Auto-approval skipped: Fayda ID {fayda_id} is already registered as {registered_da_id}."
    if other_reference:
        return f"Auto-approval skipped: Fayda ID {fayda_id} is already in submission {other_reference}."
    return None


async def _is_da_register(session, register_id: str) -> bool:
    mnemonic = (
        await session.execute(
            text("SELECT register_mnemonic FROM g2p_register_definitions WHERE register_id = :rid"),
            {"rid": register_id},
        )
    ).scalar_one_or_none()
    return mnemonic == DA_REGISTER_MNEMONIC


async def _find_duplicate(session, submission_id: str) -> tuple[str | None, str | None]:
    """(fayda_id, reason) for this submission; reason is None when it is unique."""
    fayda_id = (
        await session.execute(
            text("SELECT foundational_id FROM g2p_intake_form_das WHERE submission_id::text = :sid "
                 "AND foundational_id IS NOT NULL LIMIT 1"),
            {"sid": str(submission_id)},
        )
    ).scalar_one_or_none()
    if not fayda_id:
        return None, None

    # Rows of one file are ingested by parallel workers. Serialise on the Fayda
    # ID until this transaction commits, so two rows carrying the same ID cannot
    # both see "no duplicate" and both be approved.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:fid))"), {"fid": f"da-fayda:{fayda_id}"})

    registered = (
        await session.execute(
            text("SELECT functional_record_id FROM g2p_register_das WHERE foundational_id = :fid LIMIT 1"),
            {"fid": fayda_id},
        )
    ).scalar_one_or_none()
    other = (
        await session.execute(
            text(
                "SELECT s.application_reference FROM g2p_intake_form_das f "
                "JOIN g2p_intake_form_submissions s ON s.submission_id::text = f.submission_id::text "
                "WHERE f.foundational_id = :fid AND s.submission_id::text <> :sid "
                "AND s.draft_status = 'FINAL' AND s.approval_status IN ('PENDING', 'APPROVED') "
                "ORDER BY s.finalized_at LIMIT 1"
            ),
            {"fid": fayda_id, "sid": str(submission_id)},
        )
    ).scalar_one_or_none()
    return fayda_id, duplicate_reason(fayda_id, registered or None, other)


async def auto_approve_if_unique(service, submission, session) -> None:
    fayda_id, reason = await _find_duplicate(session, submission.submission_id)
    if reason:
        submission.remarks = reason
        session.add(submission)
        _logger.info("DA submission %s left pending: %s", submission.submission_id, reason)
        return
    upstream_approver = (
        await session.execute(
            text("SELECT upstream_approved_by FROM g2p_intake_form_das WHERE submission_id::text = :sid "
                 "AND upstream_approved_by IS NOT NULL LIMIT 1"),
            {"sid": str(submission.submission_id)},
        )
    ).scalar_one_or_none()
    await service.approve_submission_with_session(
        submission.submission_id, session,
        approved_by=f"{upstream_approver} (DA Services)" if upstream_approver else AUTO_APPROVED_BY,
    )
    _logger.info("DA submission %s auto-approved (Fayda ID %s)", submission.submission_id, fayda_id)


def _wrap_finalize(finalize):
    @functools.wraps(finalize)
    async def wrapper(self, submission_id, session, *args, **kwargs):
        submission = await finalize(self, submission_id, session, *args, **kwargs)
        bearer = kwargs.get("bearer_token")
        if (
            auto_approve_enabled()
            and is_unattended(submission, bearer)
            and await _is_da_register(session, submission.register_id)
        ):
            await auto_approve_if_unique(self, submission, session)
        return submission

    setattr(wrapper, _INSTALLED_MARKER, True)
    return wrapper


def _wrap_start_workflow(start_workflow):
    @functools.wraps(start_workflow)
    async def wrapper(self, session, submission, *args, **kwargs):
        if is_unattended(submission, kwargs.get("bearer_token")) and await _is_da_register(
            session, submission.register_id
        ):
            if auto_approve_enabled():
                # Approved by this module right after finalisation; there is
                # no user token to open an AWE request with.
                return None
            # Manual approval: open the AWE request with a service token so the
            # seeded approvers get the same tasks as for a web-form submission.
            try:
                kwargs["bearer_token"] = await get_service_token()
            except ServiceTokenUnavailable as exc:
                _logger.error("DA submission %s: %s", submission.submission_id, exc)
                raise RuntimeError(f"DA approval could not be started: {exc}") from exc
            _logger.info(
                "DA submission %s (%s) sent for approval with the service token",
                submission.submission_id, getattr(submission, "submission_source", ""),
            )
        return await start_workflow(self, session, submission, *args, **kwargs)

    setattr(wrapper, _INSTALLED_MARKER, True)
    return wrapper


def install_da_auto_approve() -> None:
    """Idempotent. Raises if the platform methods it wraps are gone, so a
    platform bump that renames them fails at startup instead of silently
    leaving imports stuck in PENDING again."""
    from openg2p_registry_core.services import G2PAweIntegrationService, G2PIntakeFormDataService

    for owner, name, wrap in (
        (G2PIntakeFormDataService, "finalize_submission_with_session", _wrap_finalize),
        (G2PAweIntegrationService, "start_intake_submission_workflow", _wrap_start_workflow),
    ):
        method = getattr(owner, name, None)
        if method is None:
            raise AttributeError(f"{owner.__name__}.{name} no longer exists; re-anchor DA auto-approve")
        if not getattr(method, _INSTALLED_MARKER, False):
            setattr(owner, name, wrap(method))
