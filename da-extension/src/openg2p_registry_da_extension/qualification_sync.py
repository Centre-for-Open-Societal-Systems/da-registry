"""Keep a DA's one-value education fields and the education & professional
records in step.

A DA's education & professional records are rows of the Qualification register
(g2p_register_qualifications), added on the form with "Add record". The DA
record still has the one-value fields education_level, specialisation,
position, joined_date and passout_year: a file import and a DA Services push
send one of each, DA Services reads them, and the register's search results
and filters show them.

Two triggers hold the two together, whatever wrote the row (approval of an
intake, a change request, an import):

- a row is added, changed or removed -> the DA record's fields take the values
  of the DA's main row: the active row with the latest passout year, then the
  latest joining date, then the newest;
- the DA record's fields are written (import, push, a change request on the
  one-value section) -> the main row takes them, or the first row is created
  when the DA has none.

Each trigger does nothing when it was fired by the other (pg_trigger_depth).
A one-off statement creates the first row of every DA saved before the list
existed. All of it is safe to run on every start.

The mirrored values are written by the trigger, not through the platform's
change request, so the register history shows the change on the side it was
made on only.
"""

from sqlalchemy import text

DA_TABLE = "g2p_register_das"
ROW_TABLE = "g2p_register_qualifications"
FIELDS = ("education_level", "specialisation", "position", "joined_date", "passout_year")

_MAIN_ORDER = "q.passout_year DESC NULLS LAST, q.joined_date DESC NULLS LAST, q.created_at DESC"
_SET_DA = ", ".join(f"{f} = main.{f}" for f in FIELDS)
_DA_DIFFERS = " OR ".join(f"d.{f} IS DISTINCT FROM main.{f}" for f in FIELDS)
_SET_ROW = ", ".join(f"{f} = NEW.{f}" for f in FIELDS)
_ROW_DIFFERS = " OR ".join(f"q.{f} IS DISTINCT FROM NEW.{f}" for f in FIELDS)
_NEW_FIELDS = ", ".join(f"NEW.{f}" for f in FIELDS)

STATEMENTS = (
    f"""
    CREATE OR REPLACE FUNCTION "public".da_fields_from_main_row(da_id text) RETURNS void AS $$
    BEGIN
        UPDATE "public"."{DA_TABLE}" d
        SET {_SET_DA}
        FROM (
            SELECT {", ".join("q." + f for f in FIELDS)}
            FROM "public"."{ROW_TABLE}" q
            WHERE q.link_internal_record_id = da_id AND q.record_status = 'ACTIVE'
            ORDER BY {_MAIN_ORDER}
            LIMIT 1
        ) main
        WHERE d.internal_record_id = da_id AND ({_DA_DIFFERS});
    END;
    $$ LANGUAGE plpgsql
    """,
    f"""
    CREATE OR REPLACE FUNCTION "public".da_qualification_row_changed() RETURNS trigger AS $$
    BEGIN
        IF pg_trigger_depth() > 1 THEN
            RETURN NULL;
        END IF;
        IF TG_OP <> 'INSERT' AND OLD.link_internal_record_id IS NOT NULL THEN
            PERFORM "public".da_fields_from_main_row(OLD.link_internal_record_id::text);
        END IF;
        IF TG_OP <> 'DELETE' AND NEW.link_internal_record_id IS NOT NULL
           AND (TG_OP = 'INSERT' OR NEW.link_internal_record_id IS DISTINCT FROM OLD.link_internal_record_id) THEN
            PERFORM "public".da_fields_from_main_row(NEW.link_internal_record_id::text);
        END IF;
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql
    """,
    f'DROP TRIGGER IF EXISTS da_qualification_row_changed ON "public"."{ROW_TABLE}"',
    f"""
    CREATE TRIGGER da_qualification_row_changed
    AFTER INSERT OR UPDATE OR DELETE ON "public"."{ROW_TABLE}"
    FOR EACH ROW EXECUTE FUNCTION "public".da_qualification_row_changed()
    """,
    f"""
    CREATE OR REPLACE FUNCTION "public".da_one_value_fields_changed() RETURNS trigger AS $$
    DECLARE
        main_id text;
    BEGIN
        IF pg_trigger_depth() > 1 THEN
            RETURN NULL;
        END IF;
        SELECT q.internal_record_id::text INTO main_id
        FROM "public"."{ROW_TABLE}" q
        WHERE q.link_internal_record_id = NEW.internal_record_id AND q.record_status = 'ACTIVE'
        ORDER BY {_MAIN_ORDER}
        LIMIT 1;
        IF NEW.education_level IS NULL AND NEW.specialisation IS NULL AND NEW.position IS NULL THEN
            -- A DA saved from the form: its rows carry the values.
            IF main_id IS NOT NULL THEN
                PERFORM "public".da_fields_from_main_row(NEW.internal_record_id::text);
            END IF;
            RETURN NULL;
        END IF;
        IF main_id IS NULL THEN
            INSERT INTO "public"."{ROW_TABLE}" (
                internal_record_id, link_internal_record_id, record_name, search_text, created_by, created_at,
                last_approved_at, last_approved_by, record_status, {", ".join(FIELDS)}
            ) VALUES (
                gen_random_uuid()::text, NEW.internal_record_id,
                concat_ws(' ', NEW.education_level, NEW.specialisation, NEW.position),
                concat_ws(' ', NEW.education_level, NEW.specialisation, NEW.position),
                NEW.created_by, NEW.created_at, NEW.last_approved_at, NEW.last_approved_by, 'ACTIVE', {_NEW_FIELDS}
            );
        ELSE
            UPDATE "public"."{ROW_TABLE}" q
            SET {_SET_ROW}
            WHERE q.internal_record_id::text = main_id AND ({_ROW_DIFFERS});
        END IF;
        RETURN NULL;
    END;
    $$ LANGUAGE plpgsql
    """,
    f'DROP TRIGGER IF EXISTS da_one_value_fields_changed ON "public"."{DA_TABLE}"',
    f"""
    CREATE TRIGGER da_one_value_fields_changed
    AFTER INSERT OR UPDATE OF {", ".join(FIELDS)} ON "public"."{DA_TABLE}"
    FOR EACH ROW EXECUTE FUNCTION "public".da_one_value_fields_changed()
    """,
    # DAs saved before the list existed: their one-value fields become the first row.
    f"""
    UPDATE "public"."{DA_TABLE}" d
    SET education_level = d.education_level
    WHERE (d.education_level IS NOT NULL OR d.specialisation IS NOT NULL OR d.position IS NOT NULL)
      AND NOT EXISTS (
          SELECT 1 FROM "public"."{ROW_TABLE}" q
          WHERE q.link_internal_record_id = d.internal_record_id AND q.record_status = 'ACTIVE')
    """,
    # DAs whose rows were saved before the triggers existed: the rows are the
    # record, so the one-value fields take the main row's values.
    f"""
    SELECT "public".da_fields_from_main_row(d.internal_record_id::text)
    FROM "public"."{DA_TABLE}" d
    WHERE EXISTS (
          SELECT 1 FROM "public"."{ROW_TABLE}" q
          WHERE q.link_internal_record_id = d.internal_record_id AND q.record_status = 'ACTIVE')
    """,
)


async def sync_qualifications(conn) -> None:
    """Install the triggers and bring existing DAs in step."""
    for statement in STATEMENTS:
        await conn.execute(text(statement))
