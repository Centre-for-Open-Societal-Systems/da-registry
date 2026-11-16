"""The startup schema steps take no table lock when nothing is missing, and
never wait on one without limit."""

import asyncio
import unittest

from sqlalchemy.exc import DBAPIError

from openg2p_registry_da_extension import startup_migration as sm


def complete_catalog():
    columns = {table: dict.fromkeys(sm.DA_COLUMNS) for table in sm.DA_TABLES}
    for table in sm.DA_TABLES:
        columns[table]["source"] = "'WEB_INTAKE'::character varying"
    columns[sm.OUTGOING_TOPICS] = dict.fromkeys(sm.OUTGOING_TOPICS_COLUMNS)
    columns[sm.RAW_PAYLOADS] = {"raw_data_json": None}
    columns["g2p_register_qualifications"] = {"education_level": None}
    indexes = {f"ix_{table}_{column}" for table in sm.DA_TABLES for column in sm.INDEXED_COLUMNS}
    indexes |= {sm.RAW_PAYLOADS_INDEX, sm.FAYDA_INDEX}
    triggers = {(table, name) for table, name, _statement in sm.TRIGGERS}
    return {"columns": columns, "indexes": indexes, "triggers": triggers}


class PendingDdlTests(unittest.TestCase):
    def test_a_complete_schema_needs_no_statement(self):
        self.assertEqual(sm.pending_ddl(complete_catalog()), [])

    def test_only_the_missing_column_is_added(self):
        catalog = complete_catalog()
        del catalog["columns"]["g2p_register_das"]["passout_year"]
        self.assertEqual(
            sm.pending_ddl(catalog),
            ['ALTER TABLE "public"."g2p_register_das" ADD COLUMN IF NOT EXISTS "passout_year" INTEGER'],
        )

    def test_default_index_and_trigger_are_planned_only_when_missing(self):
        catalog = complete_catalog()
        catalog["columns"]["g2p_intake_form_das"]["source"] = None
        catalog["indexes"].discard("ix_g2p_register_das_region_code")
        catalog["triggers"].discard(("g2p_register_das", "da_copy_da_id_to_intake"))
        plan = sm.pending_ddl(catalog)
        self.assertEqual(len(plan), 3)
        joined = "\n".join(plan)
        self.assertIn('ALTER TABLE "public"."g2p_intake_form_das" ALTER COLUMN "source" SET DEFAULT', joined)
        self.assertIn('CREATE INDEX IF NOT EXISTS "ix_g2p_register_das_region_code"', joined)
        self.assertIn("CREATE TRIGGER da_copy_da_id_to_intake", joined)

    def test_platform_tables_are_touched_only_when_they_lack_something(self):
        catalog = complete_catalog()
        del catalog["columns"][sm.OUTGOING_TOPICS]["partner_id"]
        catalog["indexes"].discard(sm.RAW_PAYLOADS_INDEX)
        plan = sm.pending_ddl(catalog)
        self.assertEqual(len(plan), 2)
        self.assertIn("outgoing_topics", plan[0])
        self.assertIn(sm.RAW_PAYLOADS_INDEX, plan[1])

    def test_a_table_that_does_not_exist_is_left_to_the_platform(self):
        self.assertEqual(sm.pending_ddl({"columns": {}, "indexes": set(), "triggers": set()}), [])

    def test_no_statement_drops_anything(self):
        empty = {"columns": {t: {} for t in list(sm.DA_TABLES) + [sm.OUTGOING_TOPICS, sm.RAW_PAYLOADS,
                                                                  "g2p_register_qualifications"]},
                 "indexes": set(), "triggers": set()}
        for statement in sm.pending_ddl(empty):
            self.assertNotIn("DROP TRIGGER", statement)
            self.assertNotIn("DROP TABLE", statement)
            self.assertNotIn("DROP INDEX", statement)


class BackfillTests(unittest.TestCase):
    def test_every_backfill_has_a_check_that_runs_first(self):
        steps = sm.backfills()
        self.assertGreaterEqual(len(steps), 15)
        for what, needed, statement in steps:
            self.assertTrue(needed.strip().startswith("SELECT EXISTS"), what)
            self.assertNotIn("ALTER TABLE", statement)

    def test_a_location_code_is_written_only_where_the_chain_has_one(self):
        _what, needed, statement = sm.geo_backfills()[0]
        for sql in (needed, statement):
            self.assertIn('"region_code" IS NULL', sql)
            self.assertIn("IS NOT NULL", sql.split('"region_code" IS NULL', 1)[1])


class _LockTimeout(Exception):
    sqlstate = "55P03"


def lock_timeout_error():
    return DBAPIError("ALTER TABLE x", {}, _LockTimeout("canceling statement due to lock timeout"))


class RetryTests(unittest.TestCase):
    def test_a_lock_timeout_is_recognised_and_other_errors_are_not(self):
        self.assertTrue(sm.is_lock_timeout(lock_timeout_error()))
        self.assertFalse(sm.is_lock_timeout(DBAPIError("x", {}, ValueError("duplicate key"))))

    def test_the_step_is_tried_again_and_then_succeeds(self):
        calls = []

        async def step():
            calls.append(1)
            if len(calls) < 3:
                raise lock_timeout_error()
            return "done"

        self.assertEqual(asyncio.run(sm.retry_on_lock_timeout(step, attempts=4, retry_seconds=0)), "done")
        self.assertEqual(len(calls), 3)

    def test_after_the_last_attempt_startup_fails_with_what_to_look_for(self):
        async def step():
            raise lock_timeout_error()

        with self.assertRaises(RuntimeError) as raised:
            asyncio.run(sm.retry_on_lock_timeout(step, attempts=2, retry_seconds=0))
        self.assertIn("idle in transaction", str(raised.exception))

    def test_another_database_error_is_not_retried(self):
        calls = []

        async def step():
            calls.append(1)
            raise DBAPIError("x", {}, ValueError("syntax error"))

        with self.assertRaises(DBAPIError):
            asyncio.run(sm.retry_on_lock_timeout(step, attempts=5, retry_seconds=0))
        self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
