"""The DA change-request service: approvals only through the approval task.

Registered ahead of the platform's G2PRegisterChangeRequestService, so its
`approve_change_request` (the direct approval behind the staff endpoints)
is refused; the workflow decision path is untouched (direct_approval.py).
While a change request is created it also keeps the id of the record the
request is for, which the position rules compare with (position_rights.py).
"""

from openg2p_registry_core.services.g2p_register_change_request_service import G2PRegisterChangeRequestService

from .component_registration import register_ahead_of_platform
from .direct_approval import DirectApprovalClosed
from .position_rights import ChangeTargetMixin


class DAChangeRequestService(ChangeTargetMixin, DirectApprovalClosed, G2PRegisterChangeRequestService):
    pass


def install_da_change_request_service() -> DAChangeRequestService:
    return register_ahead_of_platform(DAChangeRequestService)
