"""The DA-ID allocated on the register row reaches the record's intake rows.

The trigger and the one-off fill are PostgreSQL, so the behaviour is tested on
a disposable database (DA_TEST_DATABASE_URL); the rest runs anywhere.
"""

import os
import unittest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from openg2p_registry_da_extension import intake_da_id


class StatementTests(unittest.TestCase):
    def test_the_temporary_id_is_never_copied(self):
        for statement in (intake_da_id.FUNCTIONS[0], intake_da_id.BACKFILLS[0][1], intake_da_id.BACKFILLS[0][2]):
            self.assertIn("NOT LIKE 'TEMP-%'", statement)

    def test_only_the_intake_table_is_written(self):
        writes = [intake_da_id.FUNCTIONS[0], intake_da_id.BACKFILLS[0][2]]
        for statement in writes:
            self.assertIn('UPDATE "public"."g2p_intake_form_das"', statement)
            self.assertNotIn('UPDATE "public"."g2p_register_das"', statement)

    def test_the_da_id_goes_to_one_row_and_never_twice(self):
        # functional_record_id is unique on the intake table, and a record can
        # have several intake rows.
        for statement in (intake_da_id.FUNCTIONS[0], intake_da_id.BACKFILLS[0][1], intake_da_id.BACKFILLS[0][2]):
            self.assertIn("NOT EXISTS", statement)
            self.assertIn("held.functional_record_id", statement)
            self.assertIn("i.submission_id =", statement)
            self.assertIn("s.approval_status = 'APPROVED'", statement)
            self.assertIn("LIMIT 1", statement)

    def test_the_trigger_never_fails_the_register_write(self):
        self.assertIn("EXCEPTION WHEN OTHERS THEN", intake_da_id.FUNCTIONS[0])
        self.assertIn("RAISE WARNING", intake_da_id.FUNCTIONS[0])

    def test_the_function_is_replaced_and_the_trigger_only_created(self):
        # CREATE TRIGGER locks the table against writes; startup_migration.py
        # runs it only when the catalog lacks the trigger, so no DROP here.
        self.assertIn("CREATE OR REPLACE FUNCTION", intake_da_id.FUNCTIONS[0])
        table, name, statement = intake_da_id.TRIGGERS[0]
        self.assertEqual((table, name), ("g2p_register_das", "da_copy_da_id_to_intake"))
        self.assertIn("CREATE TRIGGER da_copy_da_id_to_intake", statement)
        self.assertNotIn("DROP TRIGGER", statement)

    def test_the_backfill_runs_only_when_a_row_needs_it(self):
        _what, needed, _statement = intake_da_id.BACKFILLS[0]
        self.assertTrue(needed.strip().startswith("SELECT EXISTS"))


@unittest.skipUnless(os.environ.get("DA_TEST_DATABASE_URL"), "Requires owned disposable PostgreSQL")
class CopyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine(os.environ["DA_TEST_DATABASE_URL"])
        async with self.engine.begin() as conn:
            existing = (
                await conn.execute(
                    text("SELECT to_regclass('public.g2p_register_das'), to_regclass('public.g2p_intake_form_das')")
                )
            ).one()
            if any(existing):
                self.skipTest("The DA tables exist here: not a disposable database")
            await conn.execute(text(
                'CREATE TABLE "public"."g2p_register_das" '
                "(row_id serial PRIMARY KEY, internal_record_id varchar, functional_record_id varchar)"))
            await conn.execute(text(
                'CREATE TABLE "public"."g2p_intake_form_das" (row_id serial PRIMARY KEY, '
                "submission_id uuid DEFAULT gen_random_uuid(), internal_record_id varchar, "
                "functional_record_id varchar, created_at timestamp DEFAULT clock_timestamp())"))
            # As the platform has it: one intake row per DA-ID.
            await conn.execute(text(
                'CREATE UNIQUE INDEX ix_test_intake_frid ON "public"."g2p_intake_form_das" (functional_record_id)'))
            await conn.execute(text(
                'CREATE TABLE "public"."g2p_intake_form_submissions" (submission_id uuid PRIMARY KEY, approval_status varchar)'))

    async def asyncTearDown(self):
        async with self.engine.begin() as conn:
            await conn.execute(text(
                'DROP TABLE IF EXISTS "public"."g2p_register_das", "public"."g2p_intake_form_das", '
                '"public"."g2p_intake_form_submissions"'))
            await conn.execute(text('DROP FUNCTION IF EXISTS "public".da_copy_da_id_to_intake()'))
        await self.engine.dispose()

    async def intake(self):
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text('SELECT internal_record_id, functional_record_id FROM "public"."g2p_intake_form_das" ORDER BY row_id')
            )
            return [tuple(row) for row in rows]

    async def run_sql(self, sql):
        async with self.engine.begin() as conn:
            for statement in sql.split(";"):  # asyncpg takes one command per call
                if statement.strip():
                    await conn.execute(text(statement))

    async def install(self):
        # As startup_migration.py does: function always, trigger when missing,
        # backfill when a row needs it.
        async with self.engine.begin() as conn:
            for statement in intake_da_id.FUNCTIONS:
                await conn.execute(text(statement))
            for _table, name, statement in intake_da_id.TRIGGERS:
                exists = (await conn.execute(text("SELECT 1 FROM pg_trigger WHERE tgname = :n"), {"n": name})).first()
                if not exists:
                    await conn.execute(text(statement))
            for _what, needed, statement in intake_da_id.BACKFILLS:
                if (await conn.execute(text(needed))).scalar():
                    await conn.execute(text(statement))

    async def test_submissions_approved_earlier_get_their_da_id_and_others_are_left_alone(self):
        await self.run_sql(
            """INSERT INTO "public"."g2p_register_das" (internal_record_id, functional_record_id) VALUES
               ('a', 'DA-1000000001'), ('b', 'TEMP-abc'), ('c', NULL);
               INSERT INTO "public"."g2p_intake_form_das" (internal_record_id, functional_record_id) VALUES
               ('a', NULL), ('b', NULL), ('c', NULL), ('no-register-row', NULL)"""
        )
        await self.install()
        await self.install()  # every start
        self.assertEqual(
            await self.intake(),
            [("a", "DA-1000000001"), ("b", None), ("c", None), ("no-register-row", None)],
        )

    async def test_a_record_with_several_submissions_gets_its_da_id_on_the_approved_one_only(self):
        # Dev, Nov 2026: one record id submitted four times; the DA-ID is unique on the intake table.
        await self.run_sql(
            """INSERT INTO "public"."g2p_register_das" (internal_record_id, functional_record_id) VALUES ('a', 'DA-1000000001');
               INSERT INTO "public"."g2p_intake_form_das" (submission_id, internal_record_id) VALUES
               ('00000000-0000-4000-8000-000000000001', 'a'), ('00000000-0000-4000-8000-000000000002', 'a'),
               ('00000000-0000-4000-8000-000000000003', 'a'), ('00000000-0000-4000-8000-000000000004', 'a');
               INSERT INTO "public"."g2p_intake_form_submissions" (submission_id, approval_status) VALUES
               ('00000000-0000-4000-8000-000000000001', 'REJECTED'), ('00000000-0000-4000-8000-000000000002', 'APPROVED'),
               ('00000000-0000-4000-8000-000000000003', 'PENDING'), ('00000000-0000-4000-8000-000000000004', 'PENDING')"""
        )
        await self.install()
        await self.install()  # every start: no duplicate key error
        self.assertEqual(await self.intake(), [("a", None), ("a", "DA-1000000001"), ("a", None), ("a", None)])

    async def test_without_an_approved_submission_the_latest_row_gets_it(self):
        await self.run_sql(
            """INSERT INTO "public"."g2p_register_das" (internal_record_id, functional_record_id) VALUES ('a', 'DA-1000000001');
               INSERT INTO "public"."g2p_intake_form_das" (internal_record_id, created_at) VALUES
               ('a', '2026-11-01'), ('a', '2026-11-03'), ('a', '2026-11-02')"""
        )
        await self.install()
        self.assertEqual(await self.intake(), [("a", None), ("a", "DA-1000000001"), ("a", None)])

    async def test_a_da_id_some_row_already_carries_is_not_copied_again(self):
        await self.run_sql(
            """INSERT INTO "public"."g2p_register_das" (internal_record_id, functional_record_id) VALUES ('a', 'DA-1000000001');
               INSERT INTO "public"."g2p_intake_form_das" (internal_record_id, functional_record_id, created_at) VALUES
               ('a', 'DA-1000000001', '2026-11-01'), ('a', NULL, '2026-11-05'), ('a', NULL, '2026-11-06')"""
        )
        await self.install()
        self.assertEqual(await self.intake(), [("a", "DA-1000000001"), ("a", None), ("a", None)])
        # The worker writes the register row again: still no error, nothing changes.
        await self.run_sql("""UPDATE "public"."g2p_register_das" SET functional_record_id = 'DA-1000000001'""")
        self.assertEqual(await self.intake(), [("a", "DA-1000000001"), ("a", None), ("a", None)])

    async def test_the_trigger_copies_to_one_row_when_the_record_has_several(self):
        await self.install()
        await self.run_sql(
            """INSERT INTO "public"."g2p_intake_form_das" (internal_record_id, created_at) VALUES
               ('a', '2026-11-01'), ('a', '2026-11-02');
               INSERT INTO "public"."g2p_register_das" (internal_record_id, functional_record_id) VALUES ('a', 'TEMP-abc')"""
        )
        await self.run_sql("""UPDATE "public"."g2p_register_das" SET functional_record_id = 'DA-2000000002' WHERE internal_record_id = 'a'""")
        self.assertEqual(await self.intake(), [("a", None), ("a", "DA-2000000002")])

    async def test_a_copy_that_cannot_be_made_does_not_fail_the_register_write(self):
        await self.install()
        await self.run_sql(
            """INSERT INTO "public"."g2p_intake_form_das" (internal_record_id) VALUES ('a');
               DROP TABLE "public"."g2p_intake_form_submissions";
               INSERT INTO "public"."g2p_register_das" (internal_record_id, functional_record_id) VALUES ('a', 'DA-4000000004')"""
        )
        async with self.engine.connect() as conn:
            stored = (await conn.execute(text('SELECT functional_record_id FROM "public"."g2p_register_das"'))).scalar()
        self.assertEqual(stored, "DA-4000000004")  # the register row is written
        self.assertEqual(await self.intake(), [("a", None)])  # the copy was skipped with a warning

    async def test_the_da_id_is_copied_when_the_worker_allocates_it(self):
        await self.install()
        await self.run_sql(
            """INSERT INTO "public"."g2p_intake_form_das" (internal_record_id) VALUES ('a'), ('other');
               INSERT INTO "public"."g2p_register_das" (internal_record_id, functional_record_id) VALUES ('a', 'TEMP-abc')"""
        )
        self.assertEqual(await self.intake(), [("a", None), ("other", None)])  # approved, DA-ID not allocated yet
        await self.run_sql("""UPDATE "public"."g2p_register_das" SET functional_record_id = 'DA-2000000002' WHERE internal_record_id = 'a'""")
        self.assertEqual(await self.intake(), [("a", "DA-2000000002"), ("other", None)])

    async def test_a_register_row_created_with_its_da_id_is_copied_too(self):
        await self.install()
        await self.run_sql(
            """INSERT INTO "public"."g2p_intake_form_das" (internal_record_id) VALUES ('a');
               INSERT INTO "public"."g2p_register_das" (internal_record_id, functional_record_id) VALUES ('a', 'DA-3000000003')"""
        )
        self.assertEqual(await self.intake(), [("a", "DA-3000000003")])
