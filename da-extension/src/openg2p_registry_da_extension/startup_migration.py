"""Schema steps of the DA extension at startup, without freezing the tables.

Every API and worker process runs these when it starts. They used to run
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `SET DEFAULT`, `CREATE INDEX IF
NOT EXISTS` and `DROP / CREATE TRIGGER` on every start. Each of those takes a
strong lock on its table even when there is nothing to change, and waits for
it without limit. One long-open transaction on a DA table was then enough to
keep a new pod from ever becoming ready, and while the pod waited, every other
query on that table queued behind it, so the running API hung as well.

So, in this order:

1. functions: `CREATE OR REPLACE FUNCTION`, which locks no table;
2. DDL: read the catalog first and run a statement only for what is missing.
   A complete schema takes no lock at all. What remains runs with a
   `lock_timeout` and is tried again a few times; if the lock cannot be had,
   startup fails with a clear message instead of holding the tables;
3. backfills: each in its own transaction, after the DDL, and only when a
   query finds a row that needs it. A backfill that fails, on a lock or on
   the data it meets, is logged and skipped; it never stops startup.

Several processes start together; an advisory lock lets one of them do the
work, and the others then find nothing missing.
"""

import asyncio
import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from . import intake_da_id, qualification_sync

_logger = logging.getLogger("da-startup-migration")

LOCK_TIMEOUT = "5s"
DDL_ATTEMPTS = 6
RETRY_SECONDS = 5

# Platform 1.2 core no longer exports a migration lock key; this is the value
# the older core used.
MIGRATION_LOCK_KEY = 7428190001

DA_TABLES = ("g2p_register_das", "g2p_register_history_das", "g2p_intake_form_das")

# create_all() creates missing tables but never adds columns to a table that
# already exists; these are the DA columns introduced after the first release.
DA_COLUMNS = {
    "birth_month_ec": "INTEGER",
    "birth_year_ec": "INTEGER",
    "mobile_number": "VARCHAR",
    "telegram_number": "VARCHAR",
    "alternate_number": "VARCHAR",
    "email": "VARCHAR",
    "specialisation": "VARCHAR",
    "position": "VARCHAR",
    "joined_date": "DATE",
    "passout_year": "INTEGER",
    "source": "VARCHAR",
    "upstream_reference": "VARCHAR",
    "upstream_approved_by": "VARCHAR",
    "region_name": "VARCHAR",
    "zone_name": "VARCHAR",
    "woreda_name": "VARCHAR",
    "kebele_name": "VARCHAR",
    "region_code": "VARCHAR",
    "zone_code": "VARCHAR",
    "woreda_code": "VARCHAR",
}
SOURCE_DEFAULT = "WEB_INTAKE"
# Same names SQLAlchemy uses, so a fresh database gets no second index.
INDEXED_COLUMNS = ("upstream_reference", "region_code", "zone_code", "woreda_code")

OUTGOING_TOPICS = "outgoing_topics"
OUTGOING_TOPICS_COLUMNS = ("topic_type", "partner_id")
NATIVE_COMPAT_SQL = Path(__file__).with_name("native_schema_compat.sql")

RAW_PAYLOADS = "incoming_raw_data_payloads"
RAW_PAYLOADS_INDEX = "ix_incoming_raw_data_payloads_da_reference"
FAYDA_INDEX = "ux_g2p_register_das_foundational_id_active"

FUNCTIONS = intake_da_id.FUNCTIONS + qualification_sync.FUNCTIONS
TRIGGERS = intake_da_id.TRIGGERS + qualification_sync.TRIGGERS


def is_lock_timeout(error: BaseException) -> bool:
    """Whether a database error is a lock that could not be had in time
    (SQLSTATE 55P03, lock_not_available)."""
    original = getattr(error, "orig", None)
    for candidate in (error, original, getattr(original, "__cause__", None)):
        code = getattr(candidate, "sqlstate", None) or getattr(candidate, "pgcode", None)
        if code == "55P03":
            return True
    return "lock timeout" in str(error).lower()


def pending_ddl(catalog: dict) -> list[str]:
    """The DDL statements a database still needs, from what its catalog holds.

    catalog: {"columns": {table: {column: default or None}},
              "indexes": {index name}, "triggers": {(table, trigger name)}}
    A table missing from "columns" does not exist; nothing is planned for it
    (the platform creates tables). The unique Fayda ID index is planned
    separately, because it depends on the data.
    """
    columns = catalog.get("columns", {})
    indexes = catalog.get("indexes", set())
    triggers = catalog.get("triggers", set())
    plan: list[str] = []

    if OUTGOING_TOPICS in columns and any(
        column not in columns[OUTGOING_TOPICS] for column in OUTGOING_TOPICS_COLUMNS
    ):
        plan.append(NATIVE_COMPAT_SQL.read_text(encoding="utf-8"))

    for table in DA_TABLES:
        if table not in columns:
            continue
        present = columns[table]
        for column, column_type in DA_COLUMNS.items():
            if column not in present:
                plan.append(f'ALTER TABLE "public"."{table}" ADD COLUMN IF NOT EXISTS "{column}" {column_type}')
        # Same default as the model, for tables created before it.
        if SOURCE_DEFAULT not in str(present.get("source") or ""):
            plan.append(f'ALTER TABLE "public"."{table}" ALTER COLUMN "source" SET DEFAULT \'{SOURCE_DEFAULT}\'')
        for column in INDEXED_COLUMNS:
            if f"ix_{table}_{column}" not in indexes:
                plan.append(
                    f'CREATE INDEX IF NOT EXISTS "ix_{table}_{column}" ON "public"."{table}" ("{column}")'
                )

    for table, name, statement in TRIGGERS:
        if table in columns and (table, name) not in triggers:
            plan.append(statement)

    # POST /da/get_push_status looks a push up by DA Services' reference_id,
    # which only exists inside the stored request body.
    if RAW_PAYLOADS in columns and RAW_PAYLOADS_INDEX not in indexes:
        plan.append(
            f'CREATE INDEX IF NOT EXISTS "{RAW_PAYLOADS_INDEX}" ON "public"."{RAW_PAYLOADS}" '
            "((raw_data_json->'body'->'message'->>'reference_id'))"
        )
    return plan


async def read_catalog(conn) -> dict:
    """Columns (with defaults), indexes and triggers of the tables these steps
    touch. Catalog reads only: no lock on the tables themselves."""
    tables = list(DA_TABLES) + [OUTGOING_TOPICS, RAW_PAYLOADS] + sorted({table for table, _n, _s in TRIGGERS})
    columns: dict[str, dict] = {}
    rows = await conn.execute(
        text(
            "SELECT table_name, column_name, column_default FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ANY(:tables)"
        ),
        {"tables": tables},
    )
    for table, column, default in rows:
        columns.setdefault(table, {})[column] = default
    indexes = set(
        (
            await conn.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = ANY(:tables)"),
                {"tables": tables},
            )
        ).scalars()
    )
    triggers = {
        (table, name)
        for table, name in await conn.execute(
            text(
                "SELECT c.relname, t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND NOT t.tgisinternal AND c.relname = ANY(:tables)"
            ),
            {"tables": tables},
        )
    }
    return {"columns": columns, "indexes": indexes, "triggers": triggers}


async def _plan(conn) -> list[str]:
    catalog = await read_catalog(conn)
    plan = pending_ddl(catalog)
    # Last line of defence for "one Fayda ID, one DA": the import checks catch
    # duplicates first, this stops one reaching the register anyway. Active
    # records only, so deactivating a wrong record frees its Fayda ID for the
    # real owner. Skipped (with a warning) where duplicates already exist, so
    # startup never fails on old data.
    if "g2p_register_das" in catalog["columns"] and FAYDA_INDEX not in catalog["indexes"]:
        duplicates = (
            await conn.execute(
                text(
                    'SELECT foundational_id FROM "public"."g2p_register_das" '
                    "WHERE record_status = 'ACTIVE' AND foundational_id IS NOT NULL "
                    "GROUP BY foundational_id HAVING COUNT(*) > 1 LIMIT 5"
                )
            )
        ).scalars().all()
        if duplicates:
            _logger.warning(
                "Not adding the unique Fayda ID index: active DAs share Fayda IDs %s. Resolve them and restart.",
                duplicates,
            )
        else:
            plan.append(
                f'CREATE UNIQUE INDEX IF NOT EXISTS "{FAYDA_INDEX}" ON "public"."g2p_register_das" '
                '("foundational_id") WHERE record_status = \'ACTIVE\' AND foundational_id IS NOT NULL'
            )
    return plan


async def _lock(conn) -> None:
    await conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY})


async def install_functions(engine) -> None:
    async with engine.begin() as conn:
        # Two sessions replacing one function at once fail on the catalog row.
        await _lock(conn)
        for statement in FUNCTIONS:
            await conn.execute(text(statement))


async def retry_on_lock_timeout(step, *, attempts: int = DDL_ATTEMPTS, retry_seconds: float = RETRY_SECONDS):
    """Run `step()` (a coroutine function doing DDL under a lock_timeout); when
    a lock cannot be had in time, wait and try again, and after the last
    attempt fail with a message that says what to look for."""
    for attempt in range(1, attempts + 1):
        try:
            return await step()
        except DBAPIError as error:
            if not is_lock_timeout(error):
                raise
            if attempt == attempts:
                raise RuntimeError(
                    f"DA schema changes are pending, but a table lock could not be had within {LOCK_TIMEOUT} "
                    f"in {attempts} attempts. A long-open transaction is holding a DA table: look for "
                    "'idle in transaction' sessions in pg_stat_activity, end them and start again."
                ) from error
            _logger.warning(
                "DA schema: a table is locked by another session (attempt %d of %d); trying again in %s s",
                attempt, attempts, retry_seconds,
            )
            await asyncio.sleep(retry_seconds)


async def apply_pending_ddl(engine, *, attempts: int = DDL_ATTEMPTS, retry_seconds: float = RETRY_SECONDS) -> list[str]:
    """Run the DDL the schema still needs; the statements that ran."""

    async def step() -> list[str]:
        async with engine.begin() as conn:
            if not await _plan(conn):
                return []
            await conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
            await _lock(conn)
            # Another process may have done it while this one waited.
            plan = await _plan(conn)
            for statement in plan:
                await conn.execute(text(statement))
        if plan:
            _logger.info("DA schema: applied %d statement(s)", len(plan))
        return plan

    return await retry_on_lock_timeout(step, attempts=attempts, retry_seconds=retry_seconds)


def geo_backfills() -> list[tuple[str, str, str]]:
    """Location codes of records saved before the columns existed, from the
    chain each record carries (see geo_codes.py); and the root (country) entry
    in front of chains that imports stored from the region down, which the
    form's geo widget reads from the root and shows nothing without."""
    steps = []
    chain = (
        "CASE WHEN jsonb_typeof(t.geo_code_hierarchy_json::jsonb->'hierarchy') = 'array' "
        "THEN t.geo_code_hierarchy_json::jsonb->'hierarchy' ELSE '[]'::jsonb END"
    )
    for table in DA_TABLES:
        for level in ("region", "zone", "woreda"):
            code = (
                "(SELECT substr(e->>'level_value_id', strpos(e->>'level_value_id', '-') + 1) "
                f"FROM jsonb_array_elements({chain}) e "
                f"WHERE lower(coalesce(e->>'level_mnemonic', e->>'level')) = '{level}' LIMIT 1)"
            )
            where = (
                f'WHERE t."{level}_code" IS NULL AND t.geo_code_hierarchy_json IS NOT NULL AND {code} IS NOT NULL'
            )
            steps.append((
                f"{level} code on {table}",
                f'SELECT EXISTS (SELECT 1 FROM "public"."{table}" t {where})',
                f'UPDATE "public"."{table}" t SET "{level}_code" = {code} {where}',
            ))
    root_source = " UNION ALL ".join(
        f'SELECT geo_code_hierarchy_json::jsonb->\'hierarchy\' AS h FROM "public"."{name}"' for name in DA_TABLES
    )
    root = (
        f"SELECT h->0 AS entry FROM ({root_source}) s WHERE jsonb_typeof(h) = 'array' "
        "AND lower(coalesce(h->0->>'level_mnemonic', h->0->>'level')) = 'country' LIMIT 1"
    )
    starts_at_region = (
        "jsonb_typeof(t.geo_code_hierarchy_json::jsonb->'hierarchy') = 'array' "
        "AND lower(coalesce(t.geo_code_hierarchy_json::jsonb->'hierarchy'->0->>'level_mnemonic', "
        "t.geo_code_hierarchy_json::jsonb->'hierarchy'->0->>'level')) = 'region'"
    )
    for table in DA_TABLES:
        steps.append((
            f"root of the location chain on {table}",
            f'SELECT EXISTS (SELECT 1 FROM "public"."{table}" t WHERE {starts_at_region}) AND EXISTS ({root})',
            f'WITH root AS ({root}) UPDATE "public"."{table}" t SET geo_code_hierarchy_json = jsonb_set('
            "t.geo_code_hierarchy_json::jsonb, '{hierarchy}', "
            "jsonb_build_array(root.entry) || (t.geo_code_hierarchy_json::jsonb->'hierarchy')) "
            f"FROM root WHERE {starts_at_region}",
        ))
    return steps


def backfills() -> list[tuple[str, str, str]]:
    return geo_backfills() + list(intake_da_id.BACKFILLS) + list(qualification_sync.BACKFILLS)


async def run_backfills(engine) -> list[str]:
    """Run each backfill some row needs, in its own transaction; what ran.

    A backfill repairs data saved by an earlier release; it is never needed for
    the API to work. So one that fails, on a lock or on the data it meets, is
    logged and left for the next start, and startup goes on."""
    ran = []
    for what, needed, statement in backfills():
        try:
            async with engine.begin() as conn:
                if not (await conn.execute(text(needed))).scalar():
                    continue
                await conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
                await _lock(conn)
                await conn.execute(text(statement))
            ran.append(what)
            _logger.info("DA backfill ran: %s", what)
        except DBAPIError as error:
            if is_lock_timeout(error):
                _logger.warning("DA backfill skipped, a row or table is locked (runs at the next start): %s", what)
            else:
                _logger.error(
                    "DA backfill failed and was skipped (startup continues; it runs again at the next start): "
                    "%s: %s", what, str(getattr(error, "orig", error))[:500],
                )
    return ran


async def migrate(engine) -> None:
    await install_functions(engine)
    await apply_pending_ddl(engine)
    await run_backfills(engine)
