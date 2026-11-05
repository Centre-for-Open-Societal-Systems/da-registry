import logging
import math
from typing import Optional

from iam_core.user_auth.decorators import require_permissions
from openg2p_fastapi_common.context import async_session_maker
from openg2p_fastapi_common.controller import BaseController
from openg2p_fastapi_common.schemas import G2PPaginationResponse, G2PRequest, G2PRequestBody, G2PResponseBody
from openg2p_registry_core.errors import G2PRegistryErrorCodes, G2PRegistryException
from openg2p_registry_staff_api.helpers import RequestResponseHelper
from pydantic import BaseModel

from ..config import Settings
from ..register_domain.services.exceptions import DA_SERVICES, EXCEPTION_TYPES, FILE_IMPORT, list_exceptions
from ..register_domain.services.push_status import EXCEPTION, FAILED_RETRY, lookup_push_status

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)

# Same permission as the platform's own list of incoming messages
# (/ingestion-data/search_in_ingestion_data): the answers carry DA names and
# Fayda IDs, so only staff who may read what came in can see them.
VIEW_PERMISSION = "incomingMessage:view"

DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class GetPushStatusRequestPayload(BaseModel):
    correlation_id: Optional[str] = None
    reference_id: Optional[str] = None


class GetPushStatusRequestBody(G2PRequestBody):
    request_payload: GetPushStatusRequestPayload


class GetPushStatusRequest(G2PRequest):
    request_body: GetPushStatusRequestBody


class SearchExceptionsRequestPayload(BaseModel):
    source: Optional[str] = None
    exception_type: Optional[str] = None
    state: Optional[str] = None


class SearchExceptionsRequestBody(G2PRequestBody):
    request_payload: SearchExceptionsRequestPayload


class SearchExceptionsRequest(G2PRequest):
    request_body: SearchExceptionsRequestBody


def _invalid_request(message: str):
    raise G2PRegistryException(code=G2PRegistryErrorCodes.REQUEST_VALIDATION_ERROR.value[1], message=message)


def check_exceptions_filters(payload: SearchExceptionsRequestPayload, page_number: int, page_size: int) -> None:
    if payload.source and payload.source not in (DA_SERVICES, FILE_IMPORT):
        _invalid_request(f"source must be {DA_SERVICES} or {FILE_IMPORT}")
    if payload.exception_type and payload.exception_type not in EXCEPTION_TYPES:
        _invalid_request("exception_type must be one of " + ", ".join(EXCEPTION_TYPES))
    if payload.state and payload.state not in (EXCEPTION, FAILED_RETRY):
        _invalid_request(f"state must be {EXCEPTION} or {FAILED_RETRY}")
    if page_number < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        _invalid_request(f"current_page >= 1, page_size 1-{MAX_PAGE_SIZE}")


class DAIngestStatusController(BaseController):
    """What happened to DAs that arrived without a staff user, in the staff API.

    POST /da/get_push_status: where a DA that DA Services pushed stands, by the
    correlation_id the push returned or by DA Services' own reference_id
    (latest push wins). See register_domain/services/push_status.py.

    POST /da/search_exceptions: every pushed or imported DA that is stuck
    (EXCEPTION / FAILED_RETRY), for the exceptions panel. See
    register_domain/services/exceptions.py.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.router.tags += ["/da"]
        self.router.prefix = "/da"
        self.helper = RequestResponseHelper.get_component()

        self.router.add_api_route(
            "/get_push_status", self.get_push_status, methods=["POST"], operation_id="get_da_push_status"
        )
        self.router.add_api_route(
            "/search_exceptions", self.search_exceptions, methods=["POST"], operation_id="search_da_exceptions"
        )

    @require_permissions({VIEW_PERMISSION})
    async def get_push_status(self, request: GetPushStatusRequest):
        try:
            payload = request.request_body.request_payload
            if not payload.correlation_id and not payload.reference_id:
                _invalid_request("Give correlation_id or reference_id")
            async with async_session_maker.get()() as session:
                status = await lookup_push_status(
                    session, correlation_id=payload.correlation_id, reference_id=payload.reference_id
                )
            if status is None:
                _invalid_request("No DA push found for this correlation_id / reference_id")
            return self.helper.construct_success_response(G2PResponseBody(response_payload=status), request)
        except Exception as error_exception:
            _logger.error(f"Error in get_push_status: {str(error_exception)}")
            return self.helper.construct_error_response(error_exception, request)

    @require_permissions({VIEW_PERMISSION})
    async def search_exceptions(self, request: SearchExceptionsRequest):
        try:
            payload = request.request_body.request_payload
            pagination = request.request_body.pagination_request
            page_number = pagination.current_page if pagination else 1
            page_size = pagination.page_size if pagination else DEFAULT_PAGE_SIZE
            check_exceptions_filters(payload, page_number, page_size)
            async with async_session_maker.get()() as session:
                result = await list_exceptions(
                    session,
                    source=payload.source,
                    exception_type=payload.exception_type,
                    state=payload.state,
                    page_number=page_number,
                    page_size=page_size,
                )
            total = result["total_count"]
            return self.helper.construct_success_response(
                G2PResponseBody(response_payload=result["exceptions"]),
                request,
                G2PPaginationResponse(number_of_items=total, number_of_pages=math.ceil(total / page_size)),
            )
        except Exception as error_exception:
            _logger.error(f"Error in search_exceptions: {str(error_exception)}")
            return self.helper.construct_error_response(error_exception, request)
