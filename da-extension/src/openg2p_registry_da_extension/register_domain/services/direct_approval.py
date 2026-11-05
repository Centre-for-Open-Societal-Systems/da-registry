"""Close the two staff endpoints that apply a register change without an approval task.

Core exposes two calls that write to the register on one user's say-so:

* `approve_intake_form_submission` (permission `intakeSubmission:approve`) ends
  in `approve_submission`, which marks the intake approved and queues the
  register write without looking at the approval workflow.
* `approve_change_request` and `approve_change_request_for_core_data`
  (permission `changeRequest:approve`) end in `approve_change_request`, which
  applies the change and writes the register history the same way.

Approvals must come from the workflow engine's two-stage task. The engine's
signed decision reaches `approve_submission_with_session` and
`approve_change_request_from_awe_webhook`, and the ingestion worker calls
`_approve_change_request_core`; none of those passes through the two methods
refused here, so the workflow path is unchanged. The refusal holds for every
caller, whatever roles or permissions the IAM catalog grants them.
"""

DIRECT_APPROVAL_CODE = "AWE_APPROVAL_REQUIRED"
DIRECT_APPROVAL_MESSAGE = (
    "This change is approved through its approval task. Open the task in the "
    "approvals list and decide it there; a register change is never applied "
    "by approving it directly."
)


class DirectApprovalClosedError(Exception):
    """Raised where the platform's own exception type is not importable."""

    def __init__(self, message: str = DIRECT_APPROVAL_MESSAGE, code: str = DIRECT_APPROVAL_CODE):
        super().__init__(message)
        self.message = message
        self.code = code


def direct_approval_closed() -> Exception:
    try:
        from openg2p_registry_core.errors import G2PRegistryException
    except ImportError:
        return DirectApprovalClosedError()
    return G2PRegistryException(code=DIRECT_APPROVAL_CODE, message=DIRECT_APPROVAL_MESSAGE)


class DirectApprovalClosed:
    """Mixin placed ahead of the platform services; see the module docstring."""

    async def approve_submission(self, *args, **kwargs):
        raise direct_approval_closed()

    async def approve_change_request(self, *args, **kwargs):
        raise direct_approval_closed()
