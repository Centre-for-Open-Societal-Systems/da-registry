# ruff: noqa: E402
import asyncio
import logging
import sys

from .config import Settings

_config = Settings.get_config()

from openg2p_fastapi_common.app import Initializer as BaseInitializer
from openg2p_fastapi_common.context import dbengine
from openg2p_registry_core.app import Initializer as CoreInitializer
from sqlalchemy import text

from .register_domain.factory import G2PRegisterDomainFactory
from .register_domain.models import G2PIntakeFormDA, G2PRegisterDA, G2PRegisterHistoryDA
from .register_domain.services import (
    G2PRegisterDomainServiceDA,
    install_da_auto_approve,
    install_da_own_record_guard,
    install_record_image_url_resolution,
)

_logger = logging.getLogger(_config.logging_default_logger_name)

DA_TABLES = ("g2p_register_das", "g2p_register_history_das", "g2p_intake_form_das")

# Several APIs start together and each runs the DA schema steps below, so they
# take this advisory lock one at a time. Platform 1.2 core no longer exports a
# migration lock key; this is the value the older core used.
_MIGRATION_LOCK_KEY = 7428190001


class Initializer(BaseInitializer):
    def initialize(self, **kwargs):
        super().initialize()
        CoreInitializer().initialize()

        self._patch_filter_builder()

        # Three platform bugs fixed in-process instead of patching the image;
        # see platform_overrides.py.
        from .platform_overrides import install_platform_overrides

        install_platform_overrides()

        # Intake reads return record_image_document_id but not the presigned
        # URL the register reads add; resolve it so a record photo shows on
        # the approval screen. See the function for details.
        install_record_image_url_resolution()

        # File import / partner ingestion: approve unique DAs without a user
        # token. See register_domain/services/auto_approve.py.
        install_da_auto_approve()

        # A Development Agent (token claim da_id, role Data Editor only) sees
        # and edits only their own record. See services/da_own_record.py.
        install_da_own_record_guard()

        G2PRegisterDomainFactory()
        G2PRegisterDomainServiceDA()

    def _patch_filter_builder(self):
        """Accept "true"/"false" strings for boolean filters (the staff UI sends
        strings; the platform's FilterBuilder expects real booleans)."""
        try:
            from openg2p_registry_core.services.filter_builder import FilterBuilder
            from sqlalchemy import Boolean

            orig_build_field_conditions = FilterBuilder._build_field_conditions
            orig_validate_value = FilterBuilder._validate_value

            def _to_bool(v):
                if isinstance(v, str) and v.lower() == "true":
                    return True
                if isinstance(v, str) and v.lower() == "false":
                    return False
                return v

            def patched_validate_value(this, field_config, operator, value):
                if field_config.get("filter_type") == "boolean":
                    if isinstance(value, str) and value.lower() in ("true", "false"):
                        return
                return orig_validate_value(this, field_config, operator, value)

            def patched_build_field_conditions(this, column, field_name, operators, field_config):
                is_bool_col = hasattr(column, "type") and isinstance(column.type, Boolean)
                if is_bool_col and isinstance(operators, dict):
                    operators = {
                        op: ([_to_bool(v) for v in val] if isinstance(val, list) else _to_bool(val))
                        for op, val in operators.items()
                    }
                return orig_build_field_conditions(this, column, field_name, operators, field_config)

            FilterBuilder._validate_value = patched_validate_value
            FilterBuilder._build_field_conditions = patched_build_field_conditions
            _logger.info("FilterBuilder boolean handling patched successfully")
        except Exception as e:
            _logger.warning(f"Failed to patch FilterBuilder: {e}")

    async def fastapi_app_startup(self, app):
        # Also run the idempotent migration on startup, not only on the CLI
        # `migrate` step: a deployment that overrides the container command can
        # skip that step and would then serve against a stale schema. Runs here
        # (inside the ASGI lifespan's event loop) rather than in initialize(),
        # which can fire more than once per process.
        await self._migrate_extension_tables()

        # DA push status and exceptions list for DA Services, partner API only.
        # Mounted here because every initializer builds its own FastAPI app and
        # the partner API's is the one served; this hook receives that app.
        if "openg2p_registry_partner_api" in sys.modules:
            from .partner_api import DAPushStatusController

            app.include_router(DAPushStatusController().router)
            _logger.info("Mounted GET /partner/da/status and /partner/da/exceptions")

    def migrate_database(self, args):
        asyncio.run(self._migrate_extension_tables())

    async def _migrate_extension_tables(self):
        _logger.info("Migrating DA extension tables")

        await G2PRegisterDA.create_migrate()
        await G2PRegisterHistoryDA.create_migrate()
        await G2PIntakeFormDA.create_migrate()

        # create_all() creates missing tables but never adds columns to a table
        # that already exists. Add each DA column explicitly so an existing
        # installation picks up columns introduced later.
        da_columns = {
            "birth_month_ec": "INTEGER",
            "birth_year_ec": "INTEGER",
            "mobile_number": "VARCHAR",
            "telegram_number": "VARCHAR",
            "alternate_number": "VARCHAR",
            "email": "VARCHAR",
            "specialisation": "VARCHAR",
            "position": "VARCHAR",
            "joined_date": "DATE",
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
        async with dbengine.get().begin() as conn:
            # Several APIs start together; run these steps one at a time.
            await conn.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _MIGRATION_LOCK_KEY})
            for table_name in DA_TABLES:
                for column_name, column_type in da_columns.items():
                    await conn.execute(
                        text(
                            f'ALTER TABLE "public"."{table_name}" '
                            f'ADD COLUMN IF NOT EXISTS "{column_name}" {column_type}'
                        )
                    )
                # Same default as the model, for tables created before it.
                await conn.execute(
                    text(
                        f'ALTER TABLE "public"."{table_name}" '
                        "ALTER COLUMN \"source\" SET DEFAULT 'WEB_INTAKE'"
                    )
                )
                # create_all() adds the model's indexes only to tables it creates;
                # add this one to tables created before the column existed. Same
                # name SQLAlchemy uses, so a fresh database gets no second index.
                for indexed in ("upstream_reference", "region_code", "zone_code", "woreda_code"):
                    await conn.execute(
                        text(
                            f'CREATE INDEX IF NOT EXISTS "ix_{table_name}_{indexed}" '
                            f'ON "public"."{table_name}" ("{indexed}")'
                        )
                    )
                # Fill the location codes of records saved before the columns
                # existed, from the chain each record carries (see geo_codes.py).
                # Rows that already have a code are left alone, so this is cheap
                # after the first run.
                for level in ("region", "zone", "woreda"):
                    await conn.execute(
                        text(
                            f'UPDATE "public"."{table_name}" t SET "{level}_code" = ('
                            "SELECT substr(e->>'level_value_id', strpos(e->>'level_value_id', '-') + 1) "
                            "FROM jsonb_array_elements("
                            "CASE WHEN jsonb_typeof(t.geo_code_hierarchy_json::jsonb->'hierarchy') = 'array' "
                            "THEN t.geo_code_hierarchy_json::jsonb->'hierarchy' ELSE '[]'::jsonb END) e "
                            f"WHERE lower(coalesce(e->>'level_mnemonic', e->>'level')) = '{level}' LIMIT 1) "
                            f'WHERE t."{level}_code" IS NULL AND t.geo_code_hierarchy_json IS NOT NULL'
                        )
                    )

            # GET /partner/da/status looks a push up by DA Services' reference_id,
            # which only exists inside the stored request body.
            # A platform table: skipped if the platform has not created it yet.
            await conn.execute(
                text(
                    "DO $$ BEGIN "
                    "IF to_regclass('public.incoming_raw_data_payloads') IS NOT NULL THEN "
                    'CREATE INDEX IF NOT EXISTS "ix_incoming_raw_data_payloads_da_reference" '
                    'ON "public"."incoming_raw_data_payloads" '
                    "((raw_data_json->'body'->'message'->>'reference_id')); "
                    "END IF; END $$"
                )
            )

            # Last line of defence for "one Fayda ID, one DA": the import checks
            # catch duplicates first, this stops one reaching the register anyway.
            # Active records only, so deactivating a wrong record frees its Fayda
            # ID for the real owner. Skipped (with a warning) where duplicates
            # already exist, so startup never fails on old data.
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
                    "Not adding the unique Fayda ID index: active DAs share Fayda IDs %s. "
                    "Resolve them and restart.",
                    duplicates,
                )
            else:
                await conn.execute(
                    text(
                        'CREATE UNIQUE INDEX IF NOT EXISTS "ux_g2p_register_das_foundational_id_active" '
                        'ON "public"."g2p_register_das" ("foundational_id") '
                        "WHERE record_status = 'ACTIVE' AND foundational_id IS NOT NULL"
                    )
                )
