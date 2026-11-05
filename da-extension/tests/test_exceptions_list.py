"""Exceptions list: which joined pipeline rows are listed, and how (no database)."""

import unittest
from datetime import datetime

from openg2p_registry_da_extension.register_domain.services.exceptions import (
    DA_SERVICES,
    FILE_IMPORT,
    IMPORT_FILE_DATA_MODEL_ID,
    select_exceptions,
    to_exception,
)
from openg2p_registry_da_extension.register_domain.services.push_status import (
    DA_SERVICES_DATA_MODEL_ID,
    EXCEPTION,
    FAILED_RETRY,
)

BASE = {
    "ingest_id": "i1",
    "data_model_id": IMPORT_FILE_DATA_MODEL_ID,
    "ingest_correlation_id": "c1",
    "receipt_date_time": datetime(2026, 10, 14, 9, 0),
    "classification_status": "PROCESSED",
    "classification_latest_error_code": None,
    "reference_id": None,
    "fayda_id": "770000000001",
    "name": "Abebe Kebede",
    "classified_ingest_id": "i1",
    "transformation_status": "PROCESSED",
    "transformation_latest_error_code": None,
    "ingestion_status": "PROCESSED",
    "ingestion_latest_error_code": None,
    "submission_found": "s1",
    "application_reference": "2026OCT14-1234-1",
    "approval_status": "APPROVED",
    "remarks": None,
    "last_updated_at": datetime(2026, 10, 14, 9, 1),
    "register_ingest_process_status": "PROCESSED",
    "register_ingest_process_last_error_code": None,
    "functional_record_id": None,
}


def row(**changes):
    return dict(BASE, **changes)


INVALID_KEBELE = row(
    ingest_id="i2",
    transformation_status="FAILED",
    transformation_latest_error_code="Location 'Nowhere' not found in Master Data",
    submission_found=None,
    application_reference=None,
    last_updated_at=None,
)
DUPLICATE_PUSH = row(
    ingest_id="i3",
    data_model_id=DA_SERVICES_DATA_MODEL_ID,
    reference_id="FR-DA-9",
    approval_status="PENDING",
    remarks="Fayda ID 770000000001 is already registered as DA-1.",
)
SYNC_RETRY = row(
    ingest_id="i4",
    register_ingest_process_status="PENDING",
    register_ingest_process_last_error_code="connection reset",
)


class TestToException(unittest.TestCase):
    def test_file_import_row_with_its_reason(self):
        out = to_exception(INVALID_KEBELE)
        self.assertEqual(out["source"], FILE_IMPORT)
        self.assertEqual((out["state"], out["exception_type"]), (EXCEPTION, "INVALID_KEBELE"))
        self.assertEqual((out["fayda_id"], out["name"]), ("770000000001", "Abebe Kebede"))
        self.assertEqual(out["received_at"], "2026-10-14T09:00:00")
        self.assertIsNone(out["updated_at"])

    def test_held_duplicate_push(self):
        out = to_exception(DUPLICATE_PUSH)
        self.assertEqual((out["source"], out["reference_id"]), (DA_SERVICES, "FR-DA-9"))
        self.assertEqual((out["state"], out["exception_type"]), (EXCEPTION, "DUPLICATE_IDENTITY"))

    def test_register_write_retry_is_failed_sync(self):
        out = to_exception(SYNC_RETRY)
        self.assertEqual((out["state"], out["exception_type"]), (FAILED_RETRY, "FAILED_SYNC"))

    def test_records_that_went_through_are_not_listed(self):
        # An old error left on a stage that later succeeded.
        recovered = row(ingestion_latest_error_code="timeout", functional_record_id="DA-5891503619")
        self.assertIsNone(to_exception(recovered))
        # Still on its way (waiting for approval, no remark).
        self.assertIsNone(to_exception(row(approval_status="PENDING")))


class TestSelectExceptions(unittest.TestCase):
    ROWS = [INVALID_KEBELE, DUPLICATE_PUSH, SYNC_RETRY, row(functional_record_id="DA-1")]

    def test_all_stuck_rows_in_order(self):
        out = select_exceptions(self.ROWS)
        self.assertEqual([e["correlation_id"] for e in out], ["c1", "c1", "c1"])
        self.assertEqual([e["exception_type"] for e in out], ["INVALID_KEBELE", "DUPLICATE_IDENTITY", "FAILED_SYNC"])

    def test_filters(self):
        self.assertEqual(len(select_exceptions(self.ROWS, source=DA_SERVICES)), 1)
        self.assertEqual(len(select_exceptions(self.ROWS, source=FILE_IMPORT)), 2)
        self.assertEqual(len(select_exceptions(self.ROWS, exception_type="FAILED_SYNC")), 1)
        self.assertEqual(len(select_exceptions(self.ROWS, state=FAILED_RETRY)), 1)
        self.assertEqual(select_exceptions(self.ROWS, source=DA_SERVICES, exception_type="INVALID_KEBELE"), [])


if __name__ == "__main__":
    unittest.main()
