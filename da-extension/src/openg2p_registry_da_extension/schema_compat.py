"""Existing-database additions for platform tables that predate this release."""

from pathlib import Path

from sqlalchemy import text

_SQL = Path(__file__).with_name("native_schema_compat.sql")


async def apply_native_schema_compat(connection):
    """Run the add-only platform compatibility SQL on an open connection."""
    await connection.execute(text(_SQL.read_text(encoding="utf-8")))


async def migrate_existing_schema(engine):
    async with engine.begin() as connection:
        await apply_native_schema_compat(connection)
