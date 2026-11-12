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
        for statement in (intake_da_id.STATEMENTS[0], intake_da_id.STATEMENTS[-1]):
            self.assertIn("NOT LIKE 'TEMP-%'", statement)

    def test_only_the_intake_table_is_written(self):
        writes = [s for s in intake_da_id.STATEMENTS if "UPDATE \"public\"" in s]
        self.assertEqual(len(writes), 2)
        for statement in writes:
            self.assertIn('UPDATE "public"."g2p_intake_form_das"', statement)

    def test_the_trigger_is_replaced_not_duplicated(self):
        self.assertIn("CREATE OR REPLACE FUNCTION", intake_da_id.STATEMENTS[0])
        self.assertIn("DROP TRIGGER IF EXISTS da_copy_da_id_to_intake", intake_da_id.STATEMENTS[1])


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
            for table in ("g2p_register_das", "g2p_intake_form_das"):
                await conn.execute(
                    text(f'CREATE TABLE "public"."{table}" (row_id serial PRIMARY KEY, internal_record_id varchar, functional_record_id varchar)')
                )

    async def asyncTearDown(self):
        async with self.engine.begin() as conn:
            await conn.execute(text('DROP TABLE IF EXISTS "public"."g2p_register_das", "public"."g2p_intake_form_das"'))
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
        async with self.engine.begin() as conn:
            await intake_da_id.copy_da_id_to_intake(conn)

    async def test_submissions_approved_earlier_get_their_da_id_and_others_are_left_alone(self):
        await self.run_sql(
            """INSERT INTO "public"."g2p_register_das" (internal_record_id, functional_record_id) VALUES
               ('a', 'DA-1000000001'), ('b', 'TEMP-abc'), ('c', NULL);
               INSERT INTO "public"."g2p_intake_form_das" (internal_record_id, functional_record_id) VALUES
               ('a', NULL), ('a', NULL), ('b', NULL), ('c', NULL), ('no-register-row', NULL)"""
        )
        await self.install()
        await self.install()  # every start
        self.assertEqual(
            await self.intake(),
            [("a", "DA-1000000001"), ("a", "DA-1000000001"), ("b", None), ("c", None), ("no-register-row", None)],
        )

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
