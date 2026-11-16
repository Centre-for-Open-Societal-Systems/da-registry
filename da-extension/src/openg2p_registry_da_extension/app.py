# ruff: noqa: E402
import asyncio
import logging
import sys

from .config import Settings

_config = Settings.get_config()

from openg2p_fastapi_common.app import Initializer as BaseInitializer
from openg2p_fastapi_common.context import dbengine
from openg2p_registry_core.app import Initializer as CoreInitializer

from .register_domain.factory import G2PRegisterDomainFactory
from .register_domain.models import (
    G2PIntakeFormDA,
    G2PIntakeFormDependent,
    G2PIntakeFormQualification,
    G2PRegisterDA,
    G2PRegisterDependent,
    G2PRegisterHistoryDA,
    G2PRegisterHistoryDependent,
    G2PRegisterHistoryQualification,
    G2PRegisterQualification,
)
from .register_domain.services import (
    G2PRegisterDomainServiceDA,
    G2PRegisterDomainServiceDependent,
    G2PRegisterDomainServiceQualification,
    install_da_change_request_service,
    install_da_import_approval_workflow,
    install_da_intake_guard,
)

from .schema_migration import add_missing_mapped_columns
from .startup_migration import LOCK_TIMEOUT, migrate, retry_on_lock_timeout

_logger = logging.getLogger(_config.logging_default_logger_name)


class Initializer(BaseInitializer):
    def initialize(self, **kwargs):
        super().initialize()
        CoreInitializer().initialize()

        # The temporary in-process workarounds for platform gaps, all in one
        # module; see register_domain/temporary_platform_overrides.py.
        from .register_domain.temporary_platform_overrides import install_temporary_platform_overrides

        install_temporary_platform_overrides()

        # File import / partner ingestion: open the approval workflow with a
        # service token, since no user token exists. Approval itself stays
        # with the approvers. See services/import_approval_workflow.py.
        install_da_import_approval_workflow()

        # A change request is approved only through its approval task.
        # See services/direct_approval.py.
        install_da_change_request_service()

        # A form cannot be saved with its required fields left out or sent for
        # approval incomplete; required = widget-required in the register
        # metadata. See services/da_intake_guard.py.
        install_da_intake_guard()

        G2PRegisterDomainFactory()
        G2PRegisterDomainServiceDA()
        G2PRegisterDomainServiceQualification()
        G2PRegisterDomainServiceDependent()

    async def fastapi_app_startup(self, app):
        # Also run the idempotent migration on startup, not only on the CLI
        # `migrate` step: a deployment that overrides the container command can
        # skip that step and would then serve against a stale schema. Runs here
        # (inside the ASGI lifespan's event loop) rather than in initialize(),
        # which can fire more than once per process.
        await self._migrate_extension_tables()

        # DA push status and exceptions list, staff API only: they return DA
        # names and Fayda IDs, so they sit behind the staff token and its
        # permissions, not on the partner API, which checks no caller.
        # Mounted here because every initializer builds its own FastAPI app and
        # the staff API's is the one served; this hook receives that app.
        if "openg2p_registry_staff_api" in sys.modules:
            from .staff_api import DAIngestStatusController

            app.include_router(DAIngestStatusController().router)
            _logger.info("Mounted POST /da/get_push_status and /da/search_exceptions")

    def migrate_database(self, args):
        asyncio.run(self._migrate_extension_tables())

    async def _migrate_extension_tables(self):
        _logger.info("Migrating DA extension tables")

        await G2PRegisterDA.create_migrate()
        await G2PRegisterHistoryDA.create_migrate()
        await G2PIntakeFormDA.create_migrate()
        await G2PRegisterQualification.create_migrate()
        await G2PRegisterHistoryQualification.create_migrate()
        await G2PIntakeFormQualification.create_migrate()
        await G2PRegisterDependent.create_migrate()
        await G2PRegisterHistoryDependent.create_migrate()
        await G2PIntakeFormDependent.create_migrate()

        # Add-only: any mapped column a table created by an older release lacks.
        # The catalog is read first; an ALTER runs only for a missing column,
        # with a lock timeout and retries (see startup_migration.py).
        models = [
            G2PRegisterDA,
            G2PRegisterHistoryDA,
            G2PIntakeFormDA,
            G2PRegisterQualification,
            G2PRegisterHistoryQualification,
            G2PIntakeFormQualification,
            G2PRegisterDependent,
            G2PRegisterHistoryDependent,
            G2PIntakeFormDependent,
        ]
        await retry_on_lock_timeout(
            lambda: add_missing_mapped_columns(dbengine.get(), models, lock_timeout=LOCK_TIMEOUT)
        )

        # Columns, defaults, indexes and triggers added after the first release,
        # then the data backfills: only what is missing, never waiting on a
        # table lock without limit. See startup_migration.py.
        await migrate(dbengine.get())
