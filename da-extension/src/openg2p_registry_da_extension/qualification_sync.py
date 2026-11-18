"""Keep a DA's one-value education fields and the education records in step.

A DA's education records are rows of the Qualification register
(g2p_register_qualifications), added on the form with "Add record": education
level, passout year and certificates. The DA record still has the one-value
fields education_level and passout_year: a file import and a DA Services push
send one of each, DA Services reads them, and the register's search results
and filters show them.

Position, specialisation and joining date are not part of an education record.
A person holds one position, so they are fields of the DA record itself (the
"Position and reporting" section); the rows' old columns of those names are no
longer read or written.

Two triggers hold the two together, whatever wrote the row (approval of an
intake, a change request, an import):

- a row is added, changed or removed -> the DA record's fields take the values
  of the DA's main row: the active row with the latest passout year, then the
  newest;
- the DA record's fields are written (import, push) -> the main row takes
  them, or the first row is created when the DA has none.

Each trigger does nothing when it was fired by the other (pg_trigger_depth).
A one-off statement creates the first row of every DA saved before the list
existed. startup_migration.py installs them: the functions on every start, a
trigger only when it is missing, a statement only when a row needs it.

The mirrored values are written by the trigger, not through the platform's
change request, so the register history shows the change on the side it was
made on only.
"""


DA_TABLE = "g2p_register_das"
ROW_TABLE = "g2p_register_qualifications"
FIELDS = ("education_level", "passout_year")

_MAIN_ORDER = "q.passout_year DESC NULLS LAST, q.created_at DESC"
_SET_DA = ", ".join(f"{f} = main.{f}" for f in FIELDS)
_DA_DIFFERS = " OR ".join(f"d.{f} IS DISTINCT FROM main.{f}" for f in FIELDS)
_SET_ROW = ", ".join(f"{f} = NEW.{f}" for f in FIELDS)
_ROW_DIFFERS = " OR ".join(f"q.{f} IS DISTINCT FROM NEW.{f}" for f in FIELDS)
_NEW_FIELDS = ", ".join(f"NEW.{f}" for f in FIELDS)

# Replaced on every start (no table lock), so a changed body takes effect.
FUNCTIONS = (
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
        IF NEW.education_level IS NULL AND NEW.passout_year IS NULL THEN
            -- A record saved from the form: its rows carry the values. A person
            -- whose position needs no education record has neither.
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
                concat_ws(' ', NEW.education_level, NEW.passout_year::text),
                concat_ws(' ', NEW.education_level, NEW.passout_year::text),
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
)

# (table, trigger name, statement). Created only when the catalog lacks it:
# CREATE TRIGGER locks the table against writes, so it must not run on every
# start. A trigger whose definition changes gets a new name.
TRIGGERS = (
    (ROW_TABLE, "da_qualification_row_changed", f"""
    CREATE TRIGGER da_qualification_row_changed
    AFTER INSERT OR UPDATE OR DELETE ON "public"."{ROW_TABLE}"
    FOR EACH ROW EXECUTE FUNCTION "public".da_qualification_row_changed()
    """),
    # Where it was created by an earlier release it also fires on a change of
    # position, specialisation or joining date; the function then finds nothing
    # to do, so the trigger is not replaced (CREATE TRIGGER locks the table).
    (DA_TABLE, "da_one_value_fields_changed", f"""
    CREATE TRIGGER da_one_value_fields_changed
    AFTER INSERT OR UPDATE OF {", ".join(FIELDS)} ON "public"."{DA_TABLE}"
    FOR EACH ROW EXECUTE FUNCTION "public".da_one_value_fields_changed()
    """),
)

_NO_ROW = f"""
    d.education_level IS NOT NULL
    AND NOT EXISTS (
        SELECT 1 FROM "public"."{ROW_TABLE}" q
        WHERE q.link_internal_record_id = d.internal_record_id AND q.record_status = 'ACTIVE')
"""
# A DA whose one-value fields differ from its main row.
_OUT_OF_STEP = f"""
    EXISTS (
        SELECT 1 FROM (
            SELECT {", ".join("q." + f for f in FIELDS)}
            FROM "public"."{ROW_TABLE}" q
            WHERE q.link_internal_record_id = d.internal_record_id AND q.record_status = 'ACTIVE'
            ORDER BY {_MAIN_ORDER}
            LIMIT 1
        ) main
        WHERE ({", ".join("d." + f for f in FIELDS)}) IS DISTINCT FROM ({", ".join("main." + f for f in FIELDS)}))
"""

# (what, query that is true when some row needs it, statement). The statement
# runs only when the query says so; see startup_migration.py.
BACKFILLS = (
    # DAs saved before the list existed: their one-value fields become the first row.
    (
        "first education record",
        f'SELECT EXISTS (SELECT 1 FROM "public"."{DA_TABLE}" d WHERE {_NO_ROW})',
        f'UPDATE "public"."{DA_TABLE}" d SET education_level = d.education_level WHERE {_NO_ROW}',
    ),
    # DAs whose rows were saved before the triggers existed: the rows are the
    # record, so the one-value fields take the main row's values.
    (
        "one-value education fields from the main record",
        f'SELECT EXISTS (SELECT 1 FROM "public"."{DA_TABLE}" d WHERE {_OUT_OF_STEP})',
        f'SELECT "public".da_fields_from_main_row(d.internal_record_id::text) '
        f'FROM "public"."{DA_TABLE}" d WHERE {_OUT_OF_STEP}',
    ),
)
