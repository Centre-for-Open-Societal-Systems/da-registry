"""DA records that stopped in the pipeline, for the DA Services exceptions panel.

Covers both partner intake routes: DA Services pushes and file import (CSV /
XLSX) rows. Each record is judged with push_status.derive_state, so a row here
reads exactly as GET /partner/da/status would report it; only EXCEPTION and
FAILED_RETRY rows are listed.

Only the latest attempt of a record counts, so a record that was sent again
and went through drops off the list. "The same record" is its reference_id for
a DA Services push and its Fayda ID for a file-import row, within that route.

The platform does not link an imported row back to its file or row number, so
a file-import row is identified by its Fayda ID and name.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import text

from .push_status import DA_SERVICES_DATA_MODEL_ID, EXCEPTION, FAILED_RETRY, derive_state

IMPORT_FILE_DATA_MODEL_ID = "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3fb2"

DA_SERVICES = "da_services"
FILE_IMPORT = "file_import"
SOURCES = {DA_SERVICES_DATA_MODEL_ID: DA_SERVICES, IMPORT_FILE_DATA_MODEL_ID: FILE_IMPORT}

EXCEPTION_TYPES = (
    "DUPLICATE_IDENTITY",
    "INVALID_KEBELE",
    "MISSING_MANDATORY_FIELD",
    "INVALID_FIELD",
    "REJECTED",
    "FAILED_SYNC",
)

# Latest attempt per record, joined to every pipeline stage it reached. The
# WHERE keeps rows where some stage left an error, a rejection or a held
# remark; derive_state then decides whether that still counts.
_CANDIDATES_SQL = """
WITH attempts AS (
    SELECT r.ingest_id, r.data_model_id, r.ingest_correlation_id, r.receipt_date_time,
           r.classification_status, r.classification_latest_error_code,
           p.raw_data_json->'body'->'message'->>'reference_id' AS reference_id,
           COALESCE(p.raw_data_json->'body'->'message'->'da'->>'fayda_id',
                    p.raw_data_json->'body'->>'Fayda ID') AS fayda_id,
           NULLIF(CONCAT_WS(' ',
                    COALESCE(p.raw_data_json->'body'->'message'->'da'->>'first_name', p.raw_data_json->'body'->>'Name'),
                    COALESCE(p.raw_data_json->'body'->'message'->'da'->>'father_name',
                             p.raw_data_json->'body'->>'Father Name')), '') AS name,
           ROW_NUMBER() OVER (
               PARTITION BY r.data_model_id,
                            CASE WHEN r.data_model_id = :da_services
                                 THEN p.raw_data_json->'body'->'message'->>'reference_id'
                                 ELSE p.raw_data_json->'body'->>'Fayda ID' END,
                            -- rows without a key are never merged
                            CASE WHEN COALESCE(p.raw_data_json->'body'->'message'->>'reference_id',
                                               p.raw_data_json->'body'->>'Fayda ID') IS NULL
                                 THEN r.ingest_id END
               ORDER BY r.receipt_date_time DESC
           ) AS attempt_rank
    FROM incoming_raw_data r
    LEFT JOIN incoming_raw_data_payloads p ON p.ingest_id = r.ingest_id
    WHERE r.data_model_id IN (:da_services, :file_import)
)
SELECT a.*,
       c.ingest_id AS classified_ingest_id,
       c.transformation_status, c.transformation_latest_error_code,
       c.ingestion_status, c.ingestion_latest_error_code, c.intake_form_submission_id,
       s.submission_id AS submission_found, s.application_reference, s.approval_status, s.remarks,
       s.last_updated_at, s.register_ingest_process_status, s.register_ingest_process_last_error_code,
       reg.functional_record_id
FROM attempts a
LEFT JOIN incoming_classified_data c ON c.ingest_id = a.ingest_id
LEFT JOIN g2p_intake_form_submissions s ON s.submission_id::text = c.intake_form_submission_id
LEFT JOIN LATERAL (
    SELECT rd.functional_record_id
    FROM g2p_register_history_das h
    JOIN g2p_register_das rd ON rd.internal_record_id = h.subject_internal_record_id
    WHERE h.submission_id::text = c.intake_form_submission_id
    LIMIT 1
) reg ON TRUE
WHERE a.attempt_rank = 1
  AND (a.classification_status = 'FAILED' OR a.classification_latest_error_code IS NOT NULL
       OR c.transformation_status = 'FAILED' OR c.transformation_latest_error_code IS NOT NULL
       OR c.ingestion_status = 'FAILED' OR c.ingestion_latest_error_code IS NOT NULL
       OR s.approval_status = 'REJECTED'
       OR (s.approval_status <> 'APPROVED' AND s.remarks IS NOT NULL)
       OR s.register_ingest_process_status = 'FAILED' OR s.register_ingest_process_last_error_code IS NOT NULL)
ORDER BY a.receipt_date_time DESC
"""


def to_exception(row: dict) -> Optional[dict]:
    """The exceptions-list entry for one joined row, or None when it is not stuck."""
    raw = {k: row.get(k) for k in ("classification_status", "classification_latest_error_code")}
    classified = submission = register = None
    if row.get("classified_ingest_id"):
        classified = {
            k: row.get(k)
            for k in (
                "transformation_status",
                "transformation_latest_error_code",
                "ingestion_status",
                "ingestion_latest_error_code",
            )
        }
    if row.get("submission_found"):
        submission = {
            k: row.get(k)
            for k in (
                "approval_status",
                "remarks",
                "register_ingest_process_status",
                "register_ingest_process_last_error_code",
            )
        }
    if row.get("functional_record_id"):
        register = {"functional_record_id": row["functional_record_id"]}

    state = derive_state(raw, classified, submission, register)
    if state["state"] not in (EXCEPTION, FAILED_RETRY):
        return None

    received, updated = row.get("receipt_date_time"), row.get("last_updated_at")
    return {
        "source": SOURCES.get(row.get("data_model_id")),
        "correlation_id": row.get("ingest_correlation_id"),
        "reference_id": row.get("reference_id"),
        "fayda_id": row.get("fayda_id"),
        "name": row.get("name"),
        **state,
        "application_reference": row.get("application_reference"),
        "received_at": received.isoformat() if received else None,
        "updated_at": updated.isoformat() if updated else None,
    }


def select_exceptions(
    rows,
    source: Optional[str] = None,
    exception_type: Optional[str] = None,
    state: Optional[str] = None,
) -> list[dict]:
    """Entries for the rows that are stuck, narrowed by the given filters."""
    out = []
    for row in rows:
        entry = to_exception(row)
        if entry is None:
            continue
        if source and entry["source"] != source:
            continue
        if exception_type and entry["exception_type"] != exception_type:
            continue
        if state and entry["state"] != state:
            continue
        out.append(entry)
    return out


async def list_exceptions(
    session,
    source: Optional[str] = None,
    exception_type: Optional[str] = None,
    state: Optional[str] = None,
    page_number: int = 1,
    page_size: int = 50,
) -> dict:
    """One page of stuck DA records, newest first."""
    rows = (
        await session.execute(
            text(_CANDIDATES_SQL),
            {"da_services": DA_SERVICES_DATA_MODEL_ID, "file_import": IMPORT_FILE_DATA_MODEL_ID},
        )
    ).mappings()
    entries = select_exceptions((dict(r) for r in rows), source, exception_type, state)
    start = (page_number - 1) * page_size
    return {
        "total_count": len(entries),
        "page_number": page_number,
        "page_size": page_size,
        "exceptions": entries[start : start + page_size],
    }
