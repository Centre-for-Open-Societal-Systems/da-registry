"""Region / Zone / Woreda codes of a DA (geo_codes.py) and how a DA save fills
them (G2PRegisterDomainServiceDA._sync_flattened_geo_names). The Master Data
lookup is replaced, so this runs without Master Data.

Imports openg2p_registry_core, so it runs in the container, not on a bare host.
"""

import asyncio
import json
import unittest
from unittest import mock

from openg2p_registry_da_extension.geo_codes import code_of, geo_codes
from openg2p_registry_da_extension.register_domain.services.g2p_register_domain_service_da import (
    G2PRegisterDomainServiceDA as Service,
)

CHAIN = {
    "lowest_level_value_id": "kebele-ET040301888007",
    "hierarchy": [
        {"level_mnemonic": "region", "level_value_id": "region-ET04", "level_value_mnemonic": "Oromia"},
        {"level_mnemonic": "zone", "level_value_id": "zone-ET0403", "level_value_mnemonic": "Ilu Aba Bora"},
        {"level_mnemonic": "woreda", "level_value_id": "woreda-ET040301", "level_value_mnemonic": "Darimu"},
        {"level_mnemonic": "kebele", "level_value_id": "kebele-ET040301888007", "level_value_mnemonic": "Meti Guda"},
    ],
}
CODES = {"region_code": "ET04", "zone_code": "ET0403", "woreda_code": "ET040301"}


class TestGeoCodes(unittest.TestCase):
    def test_codes_from_a_chain(self):
        self.assertEqual(geo_codes(CHAIN), CODES)

    def test_chain_stored_as_json_text(self):
        self.assertEqual(geo_codes(json.dumps(CHAIN)), CODES)

    def test_staff_form_chain_uses_level(self):
        chain = {"hierarchy": [{"level": "woreda", "level_value_id": "woreda-ET010101"}]}
        self.assertEqual(geo_codes(chain), {"region_code": None, "zone_code": None, "woreda_code": "ET010101"})

    def test_no_chain(self):
        for value in (None, "", "not json", {"hierarchy": None}, [1, 2]):
            self.assertEqual(geo_codes(value), {"region_code": None, "zone_code": None, "woreda_code": None})

    def test_code_of(self):
        self.assertEqual(code_of("woreda-ET040301"), "ET040301")
        self.assertIsNone(code_of(""))


class TestSaveFillsCodes(unittest.TestCase):
    def sync(self, record: dict, hierarchy):
        geo = mock.Mock()
        geo.get_geo_hierarchy = mock.AsyncMock(return_value=hierarchy)
        with mock.patch("openg2p_registry_core.services.G2PGeoHierarchyService.get_component", return_value=geo):
            asyncio.run(Service()._sync_flattened_geo_names(record))
        return record

    def test_codes_and_names_from_master_data(self):
        record = self.sync({"geo_lowest_level_value_id": "kebele-ET040301888007"}, CHAIN)
        self.assertEqual({k: record[k] for k in CODES}, CODES)
        self.assertEqual(record["woreda_name"], "Darimu")

    def test_lookup_failure_falls_back_to_the_saved_chain(self):
        record = self.sync({"geo_lowest_level_value_id": "kebele-ET040301888007", "geo_code_hierarchy_json": CHAIN}, None)
        self.assertEqual({k: record[k] for k in CODES}, CODES)

    def test_section_without_location_is_untouched(self):
        record = self.sync({"mobile_number": "0913919921"}, CHAIN)
        self.assertNotIn("woreda_code", record)


if __name__ == "__main__":
    unittest.main()
