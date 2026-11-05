"""Register an extension service ahead of the platform's in the component registry.

The platform resolves a service with `Service.get_component()`, which returns
the first registered instance of the class or of a subclass. An extension
service that subclasses the platform one and sits at the front is therefore
what every caller gets; no platform code is changed.
"""

from openg2p_fastapi_common.context import component_registry


def register_ahead_of_platform(service_class):
    """The single instance of `service_class`, created and put first on first use."""
    for component in component_registry:
        if type(component) is service_class:
            return component
    service = service_class()
    component_registry.remove(service)
    component_registry.insert(0, service)
    return service
