import logging
from typing import Optional

from fastapi import HTTPException
from openg2p_fastapi_common.context import async_session_maker
from openg2p_fastapi_common.controller import BaseController

from ..config import Settings
from ..register_domain.services.exceptions import DA_SERVICES, EXCEPTION_TYPES, FILE_IMPORT, list_exceptions
from ..register_domain.services.push_status import EXCEPTION, FAILED_RETRY, lookup_push_status

_config = Settings.get_config()
_logger = logging.getLogger(_config.logging_default_logger_name)


MAX_PAGE_SIZE = 200


class DAPushStatusController(BaseController):
    """GET /partner/da/status: what happened to a DA that DA Services pushed.

    Looked up by the correlation_id the push returned, or by DA Services' own
    reference_id (latest push wins). See register_domain/services/push_status.py
    for the states.

    GET /partner/da/exceptions: every pushed or imported DA that is stuck
    (EXCEPTION / FAILED_RETRY), for the exceptions panel. See
    register_domain/services/exceptions.py.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.router.tags += ["/partner"]
        self.router.prefix = "/partner"
        self.router.add_api_route("/da/status", self.get_status, methods=["GET"])
        self.router.add_api_route("/da/exceptions", self.get_exceptions, methods=["GET"])

    async def get_status(self, correlation_id: Optional[str] = None, reference_id: Optional[str] = None) -> dict:
        if not correlation_id and not reference_id:
            raise HTTPException(status_code=400, detail="Give correlation_id or reference_id")
        async with async_session_maker.get()() as session:
            status = await lookup_push_status(session, correlation_id=correlation_id, reference_id=reference_id)
        if status is None:
            raise HTTPException(status_code=404, detail="No DA push found for this correlation_id / reference_id")
        return status

    async def get_exceptions(
        self,
        source: Optional[str] = None,
        exception_type: Optional[str] = None,
        state: Optional[str] = None,
        page_number: int = 1,
        page_size: int = 50,
    ) -> dict:
        if source and source not in (DA_SERVICES, FILE_IMPORT):
            raise HTTPException(status_code=400, detail=f"source must be {DA_SERVICES} or {FILE_IMPORT}")
        if exception_type and exception_type not in EXCEPTION_TYPES:
            raise HTTPException(status_code=400, detail="exception_type must be one of " + ", ".join(EXCEPTION_TYPES))
        if state and state not in (EXCEPTION, FAILED_RETRY):
            raise HTTPException(status_code=400, detail=f"state must be {EXCEPTION} or {FAILED_RETRY}")
        if page_number < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise HTTPException(status_code=400, detail=f"page_number >= 1, page_size 1-{MAX_PAGE_SIZE}")
        async with async_session_maker.get()() as session:
            return await list_exceptions(
                session,
                source=source,
                exception_type=exception_type,
                state=state,
                page_number=page_number,
                page_size=page_size,
            )
