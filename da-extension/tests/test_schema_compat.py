"""The native schema compatibility SQL is add-only, idempotent and guarded."""

import os
import unittest
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from openg2p_registry_da_extension.schema_compat import migrate_existing_schema

# The outgoing_topics shape written by releases before 1.2.2-rc.557.
OLD_TABLE = """
CREATE TABLE outgoing_topics (
    topic_id varchar PRIMARY KEY,
    register_id varchar,
    data_model_id varchar NOT NULL,
    websub_topic varchar NOT NULL,
    description varchar,
    is_active boolean NOT NULL,
    created_at timestamp NOT NULL,
    updated_at timestamp,
    websub_register_status varchar NOT NULL,
    websub_register_datetime timestamp,
    websub_register_number_of_attempts integer NOT NULL,
    websub_register_latest_error_code varchar
)
"""
INSERT_ROW = """
INSERT INTO outgoing_topics VALUES
 (:id, :register_id, 'm', 't', NULL, true, now(), NULL, 'PENDING', NULL, 0, NULL)
"""


@unittest.skipUnless(
    os.environ.get("DA_TEST_DATABASE_URL"), "Requires owned disposable PostgreSQL"
)
class NativeSchemaCompatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        url = os.environ["DA_TEST_DATABASE_URL"]
        self.assertTrue(url.startswith("postgresql+asyncpg://"))
        # The SQL addresses public.outgoing_topics, so each test gets its own
        # disposable database.
        self.database = "da_compat_test_" + uuid4().hex
        self.admin_url = url
        self.url = url.rsplit("/", 1)[0] + "/" + self.database
        admin = create_async_engine(url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as conn:
            await conn.execute(text(f'CREATE DATABASE "{self.database}"'))
        await admin.dispose()
        self.engine = create_async_engine(self.url)

    async def asyncTearDown(self):
        await self.engine.dispose()
        admin = create_async_engine(self.admin_url, isolation_level="AUTOCOMMIT")
        async with admin.connect() as conn:
            await conn.execute(text(f'DROP DATABASE "{self.database}" WITH (FORCE)'))
        await admin.dispose()

    async def columns(self):
        async with self.engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT column_name, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = 'outgoing_topics'"
                )
            )
            return {r[0]: r for r in rows}

    async def test_adds_columns_once_and_is_idempotent(self):
        async with self.engine.begin() as conn:
            await conn.execute(text(OLD_TABLE))
            await conn.execute(text(INSERT_ROW), {"id": "t1", "register_id": "r1"})
        await migrate_existing_schema(self.engine)
        columns = await self.columns()
        self.assertEqual(columns["topic_type"][1], "NO")
        self.assertIsNone(columns["topic_type"][2])  # default dropped
        self.assertEqual(columns["partner_id"][1], "YES")
        count = len(columns)
        await migrate_existing_schema(self.engine)  # second run: no error
        self.assertEqual(len(await self.columns()), count)
        async with self.engine.connect() as conn:
            row = (await conn.execute(text("SELECT topic_id, topic_type, partner_id FROM outgoing_topics"))).one()
        self.assertEqual(tuple(row), ("t1", "REGISTER", None))

    async def test_raises_on_legacy_rows_without_register_id(self):
        async with self.engine.begin() as conn:
            await conn.execute(text(OLD_TABLE))
            await conn.execute(text(INSERT_ROW), {"id": "t1", "register_id": None})
        with self.assertRaises(Exception) as ctx:
            await migrate_existing_schema(self.engine)
        self.assertIn("Legacy outgoing topics", str(ctx.exception))
        self.assertNotIn("topic_type", await self.columns())

    async def test_no_outgoing_topics_table_is_a_no_op(self):
        await migrate_existing_schema(self.engine)
        self.assertEqual(await self.columns(), {})
