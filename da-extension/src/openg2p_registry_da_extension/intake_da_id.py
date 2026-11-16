"""Show the DA-ID on an approved intake submission.

The DA-ID is allocated after approval by the platform's worker, which writes
it to the register row only. The intake row of the same record (same
internal_record_id) keeps an empty functional_record_id, so the submissions
list, which shows the same columns as the register list, has "-" under DA-ID
for a development agent who has one.

A trigger on the register table copies the DA-ID to the record's intake rows
when it is allocated; the temporary "TEMP-..." value the register holds until
then is not copied. A one-off update fills the submissions approved before the
trigger existed. startup_migration.py installs them: the function on every
start, the trigger only when it is missing, the update only when a row needs it.
"""


REGISTER_TABLE = "g2p_register_das"
INTAKE_TABLE = "g2p_intake_form_das"
TEMPORARY_ID_PREFIX = "TEMP-"

TRIGGER_NAME = "da_copy_da_id_to_intake"

# Replaced on every start (no table lock), so a changed body takes effect.
FUNCTIONS = (
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
      AND i.functional_record_id IS DISTINCT FROM r.functional_record_id
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
