import importlib
import logging

from openg2p_registry_core.interfaces import G2PRegisterDomainFactory as CoreRegisterDomainFactory

_logger = logging.getLogger("g2p-register-domain-factory")


class G2PRegisterDomainFactory(CoreRegisterDomainFactory):
    """Core's domain factory, plus the platform components the celery worker
    leaves out.

    Saving and finalising an intake submission from a worker (file import)
    looks these up with get_component() and fails on None: the staff API's
    core Initializer registers them, the celery worker's Initializer does not
    (1.2 registers some of them itself). Core uses this class whenever the extension ships
    it (openg2p_registry_extensions.register_domain.factory), so building it
    is where the gaps get filled. A process that already has a component keeps
    it; in the staff and partner APIs this does nothing.

    Drop a name here once the worker registers it; drop the class once the
    list is empty.
    """

    _CELERY_MISSING_SERVICES = (
        "G2PDocumentService",
        "G2PAwePolicyConfigurationService",
        "G2PAweIntegrationService",
        "G2PRegisterVerificationService",
        "G2PRegisterMetadataService",
        "G2PRegisterHistoryService",
        "G2PRegisterHierarchicalService",
        "G2PTemplateService",
        "G2PScoreComputeService",
        "G2PCompletionScoreService",
    )
    _CELERY_MISSING_HELPERS = ("PatternMatcher", "AweHelper")

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._ensure_platform_components()
        # The celery worker never runs the extension Initializer, and it is the
        # process that finalises file-import submissions, so the service that opens
        # their approval workflow is registered here as well (idempotent).
        from ..services.import_approval_workflow import install_da_import_approval_workflow

        install_da_import_approval_workflow()

    @classmethod
    def _ensure_platform_components(cls):
        services = importlib.import_module("openg2p_registry_core.services")
        helpers = importlib.import_module("openg2p_registry_core.helpers")
        for module, names in ((services, cls._CELERY_MISSING_SERVICES), (helpers, cls._CELERY_MISSING_HELPERS)):
            for name in names:
                cls._register(getattr(module, name, None), name)
        generator = getattr(helpers, "ApplicationReferenceGenerator", None)
        if generator is not None and generator.get_component() is None:
            try:
                from openg2p_registry_core.config import Settings as CoreSettings

                generator(CoreSettings.get_config(strict=False).application_reference_format)
            except Exception as error:  # noqa: BLE001
                _logger.warning(f"Could not register ApplicationReferenceGenerator: {error}")

    @staticmethod
    def _register(component_class, name):
        if component_class is None:
            _logger.warning(f"Platform component {name} not found; not registered")
            return
        try:
            if component_class.get_component() is None:
                component_class()
        except Exception as error:  # noqa: BLE001
            _logger.warning(f"Could not register {name}: {error}")
