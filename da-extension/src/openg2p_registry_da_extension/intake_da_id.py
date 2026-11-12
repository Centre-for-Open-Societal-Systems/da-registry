"""Show the DA-ID on an approved intake submission.

The DA-ID is allocated after approval by the platform's worker, which writes
it to the register row only. The intake row of the same record (same
internal_record_id) keeps an empty functional_record_id, so the submissions
list, which shows the same columns as the register list, has "-" under DA-ID
for a development agent who has one.

A trigger on the register table copies the DA-ID to the record's intake rows
when it is allocated; the temporary "TEMP-..." value the register holds until
then is not copied. A one-off update fills the submissions approved before the
trigger existed. Both are safe to run on every start.
"""

from sqlalchemy import text

REGISTER_TABLE = "g2p_register_das"
INTAKE_TABLE = "g2p_intake_form_das"
TEMPORARY_ID_PREFIX = "TEMP-"

STATEMENTS = (
    f"""
    CREATE OR REPLACE FUNCTION "public".da_copy_da_id_to_intake() RETURNS trigger AS $$
    BEGIN
        IF NEW.functional_record_id IS NOT NULL
           AND NEW.functional_record_id NOT LIKE '{TEMPORARY_ID_PREFIX}%' THEN
            UPDATE "public"."{INTAKE_TABLE}"
            SET functional_record_id = NEW.functional_record_id
            WHERE internal_record_id = NEW.internal_record_id
              AND functional_record_id IS DISTINCT FROM NEW.functional_record_id;
        END IF;
        RETURN NEW;
    END;
    $$ LANGUAGE plpgsql
    """,
    f'DROP TRIGGER IF EXISTS da_copy_da_id_to_intake ON "public"."{REGISTER_TABLE}"',
    f"""
    CREATE TRIGGER da_copy_da_id_to_intake
    AFTER INSERT OR UPDATE OF functional_record_id ON "public"."{REGISTER_TABLE}"
    FOR EACH ROW EXECUTE FUNCTION "public".da_copy_da_id_to_intake()
    """,
    f"""
    UPDATE "public"."{INTAKE_TABLE}" i
    SET functional_record_id = r.functional_record_id
    FROM "public"."{REGISTER_TABLE}" r
    WHERE r.internal_record_id = i.internal_record_id
      AND r.functional_record_id IS NOT NULL
      AND r.functional_record_id NOT LIKE '{TEMPORARY_ID_PREFIX}%'
      AND i.functional_record_id IS DISTINCT FROM r.functional_record_id
    """,
)


async def copy_da_id_to_intake(conn) -> None:
    """Install the trigger and fill the submissions approved before it."""
    for statement in STATEMENTS:
        await conn.execute(text(statement))
