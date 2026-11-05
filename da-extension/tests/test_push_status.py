"""Push status: issuance state and reason from the pipeline's rows (no database)."""

import unittest

from openg2p_registry_da_extension.register_domain.services.push_status import (
    EXCEPTION,
    FAILED_RETRY,
    FAILED_SYNC,
    GENERATED,
    QUEUED,
    derive_state,
    exception_type,
)

RAW = {"classification_status": "PROCESSED", "classification_latest_error_code": None}
OK = {"transformation_status": "PROCESSED", "transformation_latest_error_code": None,
      "ingestion_status": "PROCESSED", "ingestion_latest_error_code": None}
APPROVED = {"approval_status": "APPROVED", "remarks": None,
            "register_ingest_process_status": "PROCESSED", "register_ingest_process_last_error_code": None}


def state(raw=RAW, classified=OK, submission=APPROVED, register=None):
    return derive_state(raw, classified, submission, register)


class TestDeriveState(unittest.TestCase):
    def test_registered_with_da_id(self):
        out = state(register={"functional_record_id": "DA-5891503619"})
        self.assertEqual((out["state"], out["reason"], out["exception_type"]), (GENERATED, None, None))

    def test_still_moving_is_queued(self):
        self.assertEqual(state(raw={"classification_status": "PENDING"}, classified=None)["state"], QUEUED)
        self.assertEqual(state(classified=dict(OK, ingestion_status="PENDING"), submission=None)["state"], QUEUED)
        # Approved, DA-ID not written yet (record still has its TEMP- id).
        self.assertEqual(state(register={"functional_record_id": "TEMP-abc"})["state"], QUEUED)

    def test_validation_error_retries_then_settles(self):
        retrying = state(classified=dict(OK, ingestion_status="PENDING",
                                         ingestion_latest_error_code="Email is not a valid email address"),
                         submission=None)
        self.assertEqual((retrying["state"], retrying["reason"]), (FAILED_RETRY, "Email is not a valid email address"))
        settled = state(classified=dict(OK, ingestion_status="FAILED",
                                        ingestion_latest_error_code="Email is not a valid email address"),
                        submission=None)
        self.assertEqual((settled["state"], settled["exception_type"]), (EXCEPTION, "INVALID_FIELD"))

    def test_transformation_failure_reports_its_reason(self):
        out = state(classified=dict(OK, transformation_status="FAILED", ingestion_status="NOT_APPLICABLE",
                                    transformation_latest_error_code="Missing: first_name"), submission=None)
        self.assertEqual((out["state"], out["exception_type"]), (EXCEPTION, "MISSING_MANDATORY_FIELD"))

    def test_duplicate_held_pending(self):
        remark = "Fayda ID 804512345611 is already registered as DA-5891503619."
        out = state(submission=dict(APPROVED, approval_status="PENDING", remarks=remark))
        self.assertEqual((out["state"], out["reason"], out["exception_type"]), (EXCEPTION, remark, "DUPLICATE_IDENTITY"))

    def test_waiting_for_approval_without_remark_is_queued(self):
        self.assertEqual(state(submission=dict(APPROVED, approval_status="PENDING"))["state"], QUEUED)

    def test_rejected(self):
        out = state(submission=dict(APPROVED, approval_status="REJECTED", remarks="Wrong Kebele"))
        self.assertEqual((out["state"], out["reason"], out["exception_type"]), (EXCEPTION, "Rejected: Wrong Kebele", "REJECTED"))

    def test_register_write_failure_is_retry_not_exception(self):
        out = state(submission=dict(APPROVED, register_ingest_process_status="FAILED",
                                    register_ingest_process_last_error_code="connection reset"))
        self.assertEqual((out["state"], out["reason"], out["exception_type"]),
                         (FAILED_RETRY, "connection reset", FAILED_SYNC))


class TestExceptionType(unittest.TestCase):
    def test_kinds(self):
        cases = {
            "Fayda ID 1 is already in submission 2026OCT07-1.": "DUPLICATE_IDENTITY",
            "Location 'kebele-X' not found in Master Data": "INVALID_KEBELE",
            "Required: Email": "MISSING_MANDATORY_FIELD",
            "Fayda ID (FAN): enter exactly 16 digits.": "INVALID_FIELD",
            "(sqlalchemy.dialects.postgresql.asyncpg.Error) <class 'asyncpg.exceptions.DeadlockDetectedError'>: "
            "deadlock detected": "FAILED_SYNC",
            "connection reset": "FAILED_SYNC",
            None: None,
        }
        for reason, kind in cases.items():
            with self.subTest(reason=reason):
                self.assertEqual(exception_type(reason), kind)


if __name__ == "__main__":
    unittest.main()
