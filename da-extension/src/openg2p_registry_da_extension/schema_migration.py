"""Add mapped extension columns after native table creation, without data repair.

Existing columns, types, defaults, constraints and unknown user columns remain
untouched. New columns use their mapped SQL type and stay nullable on old tables;
new tables retain the complete native model definition through create_migrate.
"""

import logging
from collections.abc import Iterable

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_logger = logging.getLogger("coss-registry-schema")


async def add_missing_mapped_columns(
    engine: AsyncEngine, model_classes: Iterable[type], lock_timeout: str | None = None
) -> list[tuple[str, str]]:
    """Add the mapped columns existing tables lack. The catalog is read first,
    so a complete schema runs no ALTER and takes no table lock. With
    `lock_timeout`, an ALTER that cannot get its lock in that time fails
    (SQLSTATE 55P03) instead of waiting and holding up every other query."""
    tables = {model.__table__.key: model.__table__ for model in model_classes}
    schema_map = (
        engine.sync_engine.get_execution_options().get("schema_translate_map") or {}
    )
    added = []
    async with engine.begin() as connection:
        for table in sorted(tables.values(), key=lambda item: item.key):
            schema = schema_map.get(table.schema, table.schema)

            def present_columns(sync_connection, name=table.name, target_schema=schema):
                inspector = sa_inspect(sync_connection)
                if not inspector.has_table(name, schema=target_schema):
                    return None
                return {
                    column["name"]
                    for column in inspector.get_columns(name, schema=target_schema)
                }

            present = await connection.run_sync(present_columns)
            if present is None:
                # Native create_migrate owns missing tables, not this pass.
                _logger.debug(
                    "Mapped table not present for add-only pass: %s", table.key
                )
                continue
            quote = connection.dialect.identifier_preparer
            table_name = quote.quote(table.name)
            if schema:
                table_name = quote.quote_schema(schema) + "." + table_name
            for column in table.columns:
                if column.name in present:
                    continue
                column_type = column.type.compile(dialect=connection.dialect)
                if lock_timeout and not added:
                    await connection.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))
                _logger.debug("Adding mapped column %s.%s", table.key, column.name)
                await connection.execute(
                    text(
                        f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {quote.quote(column.name)} {column_type}"
                    )
                )
                present.add(column.name)
                added.append((table.key, column.name))
    return added
