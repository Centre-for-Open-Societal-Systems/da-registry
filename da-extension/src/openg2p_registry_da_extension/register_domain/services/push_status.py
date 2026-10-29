"""Where a DA sent by DA Services (POST /partner/ingest_data) stands now.

The registry answers a push with a correlation_id only; validation, the Fayda
duplicate check and the DA-ID happen afterwards in the celery pipeline. This
reads that pipeline's own tables and reports one of the issuance states the
DA-28 acceptance criteria name:

  QUEUED        received, still being processed (or waiting for approval)
  GENERATED     registered; da_id is set
  EXCEPTION     stopped with a reason: invalid data, unknown Kebele, duplicate
                Fayda ID, or rejected. Needs a corrected record, not a retry.
  FAILED_RETRY  an attempt failed and the platform is retrying it

A validation error is retried by the platform like any other error, so a bad
record reads FAILED_RETRY (with its reason) for a few minutes before it settles
as EXCEPTION.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text

DA_SERVICES_DATA_MODEL_ID = "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb5"

QUEUED = "QUEUED"
GENERATED = "GENERATED"
EXCEPTION = "EXCEPTION"
FAILED_RETRY = "FAILED_RETRY"

# exception_type when the record is fine but the registry failed to process it:
# an approved record not yet written into the register (whatever the message),
# or a database / connection error at any stage.
FAILED_SYNC = "FAILED_SYNC"

# Lowercase markers of a technical failure in a stage's error text.
_SYSTEM_ERROR_MARKERS = ("sqlalchemy", "asyncpg", "psycopg", "deadlock", "connection", "timed out", "timeout")

_DONE = "PROCESSED"
_FAILED = "FAILED"


def exception_type(reason: Optional[str]) -> Optional[str]:
    """Group a reason into the exception kinds the DA Services panel shows.
    Matches the registry's own messages (enricher, domain validation, duplicate checks)."""
    if not reason:
        return None
    text_ = reason.lower()
    if any(marker in text_ for marker in _SYSTEM_ERROR_MARKERS):
        return FAILED_SYNC
    if "already registered" in text_ or "already in submission" in text_:
        return "DUPLICATE_IDENTITY"
    if "not found in master data" in text_:
        return "INVALID_KEBELE"
    if text_.startswith("missing:") or text_.startswith("required:"):
        return "MISSING_MANDATORY_FIELD"
    if text_.startswith("rejected"):
        return "REJECTED"
    return "INVALID_FIELD"


def _failure(status: Optional[str], error: Optional[str]) -> Optional[tuple[str, str]]:
    """(state, reason) for one pipeline stage, or None when the stage is fine."""
    if status == _FAILED:
        return EXCEPTION, error or "Processing failed"
    if error and status != _DONE:
        return FAILED_RETRY, error
    return None


def derive_state(raw: dict, classified: Optional[dict], submission: Optional[dict], register: Optional[dict]) -> dict:
    """State and reason from the rows the pipeline wrote for one push."""

    def result(state, reason=None, type_=None):
        kind = None if state == GENERATED else (type_ or exception_type(reason))
        return {"state": state, "reason": reason, "exception_type": kind}

    stage = _failure(raw.get("classification_status"), raw.get("classification_latest_error_code"))
    if stage:
        return result(*stage)
    if classified is None:
        return result(QUEUED)

    for prefix in ("transformation", "ingestion"):
        stage = _failure(classified.get(f"{prefix}_status"), classified.get(f"{prefix}_latest_error_code"))
        if stage:
            return result(*stage)
    if submission is None:
        return result(QUEUED)

    approval = submission.get("approval_status")
    if approval == "REJECTED":
        return result(EXCEPTION, "Rejected: " + (submission.get("remarks") or "no reason given"))
    if approval != "APPROVED":
        # A remark on a submission still waiting for approval says why it is held (for example a duplicate Fayda ID).
        remarks = submission.get("remarks")
        return result(EXCEPTION, remarks) if remarks else result(QUEUED)

    if register and (register.get("functional_record_id") or "").startswith("DA-"):
        return result(GENERATED)
    stage = _failure(submission.get("register_ingest_process_status"), submission.get("register_ingest_process_last_error_code"))
    if stage:
        # Writing an approved record into the register is not a data problem:
        # the record is fine, it just has not reached the register yet.
        return result(FAILED_RETRY, stage[1], FAILED_SYNC)
    return result(QUEUED)


async def _one(session, sql: str, **params) -> Optional[dict]:
    row = (await session.execute(text(sql), params)).mappings().first()
    return dict(row) if row else None


async def lookup_push_status(session, correlation_id: Optional[str] = None, reference_id: Optional[str] = None) -> Optional[dict]:
    """Status of the latest push with this correlation_id or DA Services reference_id; None if unknown."""
    if correlation_id:
        where, params = "r.ingest_correlation_id = :value", {"value": correlation_id}
    else:
        where = "(p.raw_data_json->'body'->'message'->>'reference_id') = :value AND r.data_model_id = :data_model"
        params = {"value": reference_id, "data_model": DA_SERVICES_DATA_MODEL_ID}

    raw = await _one(
        session,
        "SELECT r.ingest_id, r.ingest_correlation_id, r.receipt_date_time, r.classification_status, "
        "r.classification_latest_error_code, "
        "(p.raw_data_json->'body'->'message'->>'reference_id') AS reference_id "
        "FROM incoming_raw_data r LEFT JOIN incoming_raw_data_payloads p ON p.ingest_id = r.ingest_id "
        f"WHERE {where} ORDER BY r.receipt_date_time DESC LIMIT 1",
        **params,
    )
    if raw is None:
        return None

    classified = await _one(
        session,
        "SELECT transformation_status, transformation_latest_error_code, ingestion_status, "
        "ingestion_latest_error_code, intake_form_submission_id "
        "FROM incoming_classified_data WHERE ingest_id = :ingest_id",
        ingest_id=raw["ingest_id"],
    )
    submission = register = None
    if classified and classified.get("intake_form_submission_id"):
        submission = await _one(
            session,
            "SELECT application_reference, approval_status, remarks, last_updated_at, "
            "register_ingest_process_status, register_ingest_process_last_error_code "
            "FROM g2p_intake_form_submissions WHERE submission_id::text = :submission_id",
            submission_id=classified["intake_form_submission_id"],
        )
        register = await _one(
            session,
            "SELECT r.functional_record_id, r.record_status "
            "FROM g2p_register_history_das h JOIN g2p_register_das r "
            "ON r.internal_record_id = h.subject_internal_record_id "
            "WHERE h.submission_id::text = :submission_id LIMIT 1",
            submission_id=classified["intake_form_submission_id"],
        )

    state = derive_state(raw, classified, submission, register)
    generated = state["state"] == GENERATED
    return {
        "correlation_id": raw["ingest_correlation_id"],
        "reference_id": raw.get("reference_id"),
        **state,
        "da_id": register["functional_record_id"] if generated else None,
        "record_status": register.get("record_status") if generated else None,
        "application_reference": (submission or {}).get("application_reference"),
        "received_at": raw["receipt_date_time"].isoformat() if raw.get("receipt_date_time") else None,
        "updated_at": submission["last_updated_at"].isoformat() if submission and submission.get("last_updated_at") else None,
    }
