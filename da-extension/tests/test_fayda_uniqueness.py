"""One DA per Fayda ID, checked when a DA record is saved (fayda_uniqueness and
G2PRegisterDomainServiceDA._check_fayda_unique). The database lookup is
replaced, so this runs without a database.

Imports openg2p_registry_core, so it runs in the container, not on a bare host.
"""

import asyncio
import unittest
from unittest import mock

from openg2p_registry_core.errors import G2PRegistryException
from openg2p_registry_da_extension.register_domain.services import g2p_register_domain_service_da as service_module
from openg2p_registry_da_extension.register_domain.services.fayda_uniqueness import duplicate_message

Service = service_module.G2PRegisterDomainServiceDA


def check(record: dict, owner: tuple):
    lookup = mock.AsyncMock(return_value=owner)
    with mock.patch.object(service_module, "find_fayda_owner", lookup):
        asyncio.run(Service._check_fayda_unique(record))
    return lookup


class TestFaydaUnique(unittest.TestCase):
    def test_unique_fayda_id_passes(self):
        lookup = check({"foundational_id": "889065919921", "internal_record_id": ""}, (None, None))
        lookup.assert_awaited_once_with("889065919921", "")

    def test_registered_fayda_id_is_refused(self):
        with self.assertRaises(G2PRegistryException) as raised:
            check({"foundational_id": "960214350002"}, ("DA-6170653590", None))
        self.assertIn("already registered as DA-6170653590", str(raised.exception.message))

    def test_fayda_id_in_another_submission_is_refused(self):
        with self.assertRaises(G2PRegistryException) as raised:
            check({"foundational_id": "960214350002"}, (None, "2026OCT05-091557"))
        self.assertIn("already in submission 2026OCT05-091557", str(raised.exception.message))

    def test_own_record_is_left_out_of_the_lookup(self):
        lookup = check({"foundational_id": "889065919921", "internal_record_id": "0cafd44c"}, (None, None))
        lookup.assert_awaited_once_with("889065919921", "0cafd44c")

    def test_section_without_fayda_id_skips_the_lookup(self):
        lookup = check({"mobile_number": "0913919921"}, ("DA-1", None))
        lookup.assert_not_awaited()

    def test_message_wording_maps_to_duplicate_identity(self):
        # push_status.exception_type looks for these phrases.
        self.assertIn("already registered", duplicate_message("1", "DA-1", None))
        self.assertIn("already in submission", duplicate_message("1", None, "REF"))
        self.assertIsNone(duplicate_message("1", None, None))


if __name__ == "__main__":
    unittest.main()
