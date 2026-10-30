"""The DA push status and exceptions endpoints live in the staff API, behind a permission."""

import importlib.util
import unittest

from iam_core.user_auth.decorators import endpoint_requires_token, get_required_permissions
from openg2p_registry_core.errors import G2PRegistryException
from openg2p_registry_da_extension.staff_api.da_ingest_status_controller import (
    MAX_PAGE_SIZE,
    VIEW_PERMISSION,
    DAIngestStatusController,
    SearchExceptionsRequestPayload,
    check_exceptions_filters,
)


class DAIngestStatusControllerTest(unittest.TestCase):
    def test_both_handlers_need_the_incoming_message_permission(self):
        for handler in (DAIngestStatusController.get_push_status, DAIngestStatusController.search_exceptions):
            self.assertEqual(get_required_permissions(handler), {VIEW_PERMISSION})
            self.assertTrue(endpoint_requires_token(handler))
        self.assertEqual(VIEW_PERMISSION, "incomingMessage:view")

    def test_not_on_the_partner_api_any_more(self):
        self.assertIsNone(importlib.util.find_spec("openg2p_registry_da_extension.partner_api"))


class CheckExceptionsFiltersTest(unittest.TestCase):
    def test_accepts_known_filters(self):
        check_exceptions_filters(
            SearchExceptionsRequestPayload(source="file_import", exception_type="INVALID_KEBELE", state="EXCEPTION"),
            1,
            MAX_PAGE_SIZE,
        )
        check_exceptions_filters(SearchExceptionsRequestPayload(), 1, 50)

    def test_refuses_unknown_values(self):
        for payload, page, size in (
            (SearchExceptionsRequestPayload(source="odk"), 1, 50),
            (SearchExceptionsRequestPayload(exception_type="TYPO"), 1, 50),
            (SearchExceptionsRequestPayload(state="QUEUED"), 1, 50),
            (SearchExceptionsRequestPayload(), 0, 50),
            (SearchExceptionsRequestPayload(), 1, MAX_PAGE_SIZE + 1),
        ):
            with self.assertRaises(G2PRegistryException):
                check_exceptions_filters(payload, page, size)


if __name__ == "__main__":
    unittest.main()
