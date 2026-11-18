import sys as _sys

__version__ = "1.0.3"
__variant__ = "da"

# The celery worker imports this package (REGISTRY_EXTENSION_MODULE) but never
# runs the extension Initializer, and from platform 1.2 its own Initializer
# builds core's domain factory instead of ours. Build ours in every pool process
# once the worker is set up: it registers the platform components the worker
# leaves out and registers the DA import approval workflow service. Both steps are idempotent.
if "openg2p_registry_celery_worker" in _sys.modules:
    from celery.signals import worker_process_init as _worker_process_init

    @_worker_process_init.connect(weak=False)
    def _set_up_da_worker(**_kwargs):
        from .register_domain.factory import G2PRegisterDomainFactory

        G2PRegisterDomainFactory()

    # A Keycloak account for each person in the register (keycloak_users.py):
    # after the platform's task that gives a record its DA-ID, and again on a
    # timer for what failed. Off unless DA_KEYCLOAK_USERS_ENABLED is "true".
    from celery.signals import task_postrun as _task_postrun
    from celery.signals import worker_ready as _worker_ready

    @_task_postrun.connect(weak=False)
    def _da_keycloak_users_after_task(sender=None, **_kwargs):
        from . import keycloak_users

        if getattr(sender, "name", "") in keycloak_users.TRIGGER_TASKS:
            keycloak_users.run_quietly()

    @_worker_ready.connect(weak=False)
    def _da_keycloak_users_retry_timer(**_kwargs):
        from . import keycloak_users

        keycloak_users.start_retry_timer()
