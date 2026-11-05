"""One DA per Fayda ID, checked when a DA record is saved.

The unique index on active register rows is the last guard, but it only fires
when an approved submission is written to the register: a staff user could
fill and submit a form for a Fayda ID that is already registered, an approver
could approve it, and the DA would then never be created. Checking at save
time stops it on the identity section instead, with a reason the user can act on.

The record being saved is left out by its internal_record_id, so re-saving a
section of the same submission, or a change request on the DA itself, is not
reported as a duplicate of itself.
"""

from openg2p_fastapi_common.context import dbengine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

# A submission that already holds the Fayda ID: waiting for approval, or
# approved and not yet written to the register.
_OTHER_SUBMISSION_SQL = text(
    "SELECT s.application_reference FROM g2p_intake_form_das f "
    "JOIN g2p_intake_form_submissions s ON s.submission_id::text = f.submission_id::text "
    "WHERE f.foundational_id = :fid AND f.internal_record_id::text <> :own "
    "AND s.draft_status = 'FINAL' AND (s.approval_status = 'PENDING' OR "
    "(s.approval_status = 'APPROVED' AND s.register_ingest_process_status NOT IN ('PROCESSED', 'FAILED'))) "
    "ORDER BY s.finalized_at LIMIT 1"
)
_REGISTERED_SQL = text(
    "SELECT functional_record_id FROM g2p_register_das "
    "WHERE foundational_id = :fid AND record_status = 'ACTIVE' AND internal_record_id::text <> :own LIMIT 1"
)


def duplicate_message(fayda_id: str, registered_da_id: str | None, other_reference: str | None) -> str | None:
    # The wording ("already registered", "already in submission") is what the
    # push status API maps to DUPLICATE_IDENTITY.
    if registered_da_id:
        return f"Fayda ID {fayda_id} is already registered as {registered_da_id}. Open that record instead of registering the development agent again."
    if other_reference:
        return f"Fayda ID {fayda_id} is already in submission {other_reference}, which is waiting for a decision."
    return None


async def find_fayda_owner(fayda_id: str, own_record_id: str) -> tuple[str | None, str | None]:
    """(registered DA-ID, other submission reference) already holding this Fayda ID."""
    params = {"fid": fayda_id, "own": own_record_id or ""}
    session_maker = async_sessionmaker(dbengine.get(), expire_on_commit=False)
    async with session_maker() as session:
        registered = (await session.execute(_REGISTERED_SQL, params)).scalar_one_or_none()
        if registered:
            return registered, None
        other = (await session.execute(_OTHER_SUBMISSION_SQL, params)).scalar_one_or_none()
        return None, other
