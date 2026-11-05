"""The DA change-request service: approvals only through the approval task.

Registered ahead of the platform's G2PRegisterChangeRequestService, so its
`approve_change_request` (the direct approval behind the staff endpoints)
is refused; the workflow decision path is untouched (direct_approval.py).
"""

from openg2p_registry_core.services.g2p_register_change_request_service import G2PRegisterChangeRequestService

from .component_registration import register_ahead_of_platform
from .direct_approval import DirectApprovalClosed


class DAChangeRequestService(DirectApprovalClosed, G2PRegisterChangeRequestService):
    pass


def install_da_change_request_service() -> DAChangeRequestService:
    return register_ahead_of_platform(DAChangeRequestService)
