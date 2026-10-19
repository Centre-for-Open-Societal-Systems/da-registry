"""DA auto-approve: which submissions qualify and what a duplicate records.

The database side (duplicate lookup, approval) is covered by the end-to-end
import test; these check the decisions. Imports the extension, so it runs in
the container.
"""

import os
import unittest
from types import SimpleNamespace
from unittest import mock

from openg2p_registry_da_extension.register_domain.services import auto_approve


class TestUnattended(unittest.TestCase):
    def test_file_import_and_partner_ingestion_qualify(self):
        self.assertTrue(auto_approve.is_unattended(SimpleNamespace(submission_source="PARTNER"), None))
        self.assertTrue(auto_approve.is_unattended(SimpleNamespace(submission_source="partner"), "  "))

    def test_web_intake_keeps_its_approval(self):
        self.assertFalse(auto_approve.is_unattended(SimpleNamespace(submission_source="STAFF_PORTAL"), None))
        self.assertFalse(auto_approve.is_unattended(SimpleNamespace(submission_source="STAFF_PORTAL"), "tok"))

    def test_a_user_token_means_a_person_is_behind_it(self):
        self.assertFalse(auto_approve.is_unattended(SimpleNamespace(submission_source="PARTNER"), "tok"))


class TestDuplicateReason(unittest.TestCase):
    def test_unique_has_no_reason(self):
        self.assertIsNone(auto_approve.duplicate_reason("412345678901", None, None))

    def test_registered_fayda_names_the_da_id(self):
        reason = auto_approve.duplicate_reason("412345678901", "DA-1234567890", "2026OCT06-000001")
        self.assertEqual(reason, "Auto-approval skipped: Fayda ID 412345678901 is already registered as DA-1234567890.")

    def test_fayda_in_another_submission_names_it(self):
        reason = auto_approve.duplicate_reason("412345678901", None, "2026OCT06-000001")
        self.assertIn("already in submission 2026OCT06-000001", reason)


class TestSwitch(unittest.TestCase):
    def test_on_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(auto_approve.auto_approve_enabled())

    def test_can_be_switched_off(self):
        for value in ("false", "0", "no", "off"):
            with mock.patch.dict(os.environ, {"DA_AUTO_APPROVE_IMPORTS": value}):
                self.assertFalse(auto_approve.auto_approve_enabled())


class TestInstall(unittest.TestCase):
    def test_install_wraps_both_platform_methods_once(self):
        from openg2p_registry_core.services import G2PAweIntegrationService, G2PIntakeFormDataService

        auto_approve.install_da_auto_approve()
        first = G2PIntakeFormDataService.finalize_submission_with_session
        auto_approve.install_da_auto_approve()
        self.assertIs(G2PIntakeFormDataService.finalize_submission_with_session, first)
        self.assertTrue(getattr(first, auto_approve._INSTALLED_MARKER, False))
        self.assertTrue(getattr(G2PAweIntegrationService.start_intake_submission_workflow,
                                auto_approve._INSTALLED_MARKER, False))


if __name__ == "__main__":
    unittest.main()
