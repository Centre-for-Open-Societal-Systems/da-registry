"""Show the DA-ID on the approved intake submission of a development agent.

The DA-ID is allocated after approval by the platform's worker, which writes
it to the register row only. The intake row of the same record (same
internal_record_id) keeps an empty functional_record_id, so the submissions
list, which shows the same columns as the register list, has "-" under DA-ID
for a development agent who has one.

A trigger on the register table copies the DA-ID to the record's intake row
when it is allocated; the temporary "TEMP-..." value the register holds until
then is not copied. A one-off update fills the submissions approved before the
trigger existed.

One row only. A record can have several intake rows (a DA submitted again
under the same record id, as the sample loader does), and the platform keeps
functional_record_id unique on the intake table. So the DA-ID goes to one row
of the record: the row of its approved submission, else its latest row; and
not at all when some intake row already carries that DA-ID. The trigger never
fails the register write: a copy that cannot be made is a warning.

startup_migration.py installs them: the function on every start, the trigger
only when it is missing, the update only when a row needs it.
"""


REGISTER_TABLE = "g2p_register_das"
INTAKE_TABLE = "g2p_intake_form_das"
TEMPORARY_ID_PREFIX = "TEMP-"

SUBMISSION_TABLE = "g2p_intake_form_submissions"
TRIGGER_NAME = "da_copy_da_id_to_intake"


def _one_row_of(record_id: str) -> str:
    """The submission_id of the intake row that gets the record's DA-ID: its
    approved submission, else its latest row."""
    return f"""(
        SELECT pick.submission_id
        FROM "public"."{INTAKE_TABLE}" pick
        LEFT JOIN "public"."{SUBMISSION_TABLE}" s ON s.submission_id = pick.submission_id
        WHERE pick.internal_record_id = {record_id}
        ORDER BY (s.approval_status = 'APPROVED') DESC NULLS LAST, pick.created_at DESC NULLS LAST,
                 pick.submission_id
        LIMIT 1)"""


def _not_held(da_id: str) -> str:
    """No intake row carries this DA-ID yet (it is unique on the intake table)."""
    return f"""NOT EXISTS (
        SELECT 1 FROM "public"."{INTAKE_TABLE}" held WHERE held.functional_record_id = {da_id})"""


# Replaced on every start (no table lock), so a changed body takes effect.
FUNCTIONS = (
    f"""
    CREATE OR REPLACE FUNCTION "public".da_copy_da_id_to_intake() RETURNS trigger AS $$
    BEGIN
        IF NEW.functional_record_id IS NOT NULL
           AND NEW.functional_record_id NOT LIKE '{TEMPORARY_ID_PREFIX}%' THEN
            BEGIN
                UPDATE "public"."{INTAKE_TABLE}" i
                SET functional_record_id = NEW.functional_record_id
                WHERE i.internal_record_id = NEW.internal_record_id
                  AND {_not_held("NEW.functional_record_id")}
                  AND i.submission_id = {_one_row_of("NEW.internal_record_id")};
            EXCEPTION WHEN OTHERS THEN
                -- The DA-ID on the submission is for display; it must never
                -- stop the register row from being written.
                RAISE WARNING 'DA-ID % was not copied to its intake submission: %',
                    NEW.functional_record_id, SQLERRM;
            END;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
)

# (table, trigger name, statement). Created only when the catalog lacks it:
# CREATE TRIGGER locks the table against writes, so it must not run on every
# start. A trigger whose definition changes gets a new name.
TRIGGERS = (
    (
        REGISTER_TABLE,
        TRIGGER_NAME,
        f"""
        CREATE TRIGGER {TRIGGER_NAME}
        AFTER INSERT OR UPDATE OF functional_record_id ON "public"."{REGISTER_TABLE}"
        FOR EACH ROW EXECUTE FUNCTION "public".da_copy_da_id_to_intake()
        """,
    ),
)

_NEEDS_COPY = f"""
    FROM "public"."{REGISTER_TABLE}" r
    WHERE r.internal_record_id = i.internal_record_id
      AND r.functional_record_id IS NOT NULL
      AND r.functional_record_id NOT LIKE '{TEMPORARY_ID_PREFIX}%'
      AND {_not_held("r.functional_record_id")}
      AND i.submission_id = {_one_row_of("r.internal_record_id")}
"""

# (what, query that is true when some row needs it, statement). The statement
# runs only when the query says so; see startup_migration.py.
BACKFILLS = (
    (
        "DA-ID on approved submissions",
        f'SELECT EXISTS (SELECT 1 FROM "public"."{INTAKE_TABLE}" i WHERE EXISTS (SELECT 1 {_NEEDS_COPY}))',
        f'UPDATE "public"."{INTAKE_TABLE}" i SET functional_record_id = r.functional_record_id {_NEEDS_COPY}',
    ),
)
