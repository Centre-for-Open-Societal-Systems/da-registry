"""DCI search result template (templates/openg2p_da_to_dci.json.j2): the
location codes DA Services filters and scopes on.

Needs jinja2, so it runs in the container like the other extension tests.
"""

import json
import pathlib
import unittest

from jinja2 import Environment

import openg2p_registry_da_extension

# The installed package's copy (in the image), else the source tree's.
_NAME = "templates/openg2p_da_to_dci.json.j2"
TEMPLATE = pathlib.Path(openg2p_registry_da_extension.__file__).parent / _NAME
if not TEMPLATE.exists():
    TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "src/openg2p_registry_da_extension" / _NAME


def render(record: dict) -> dict:
    template = Environment().from_string(TEMPLATE.read_text())
    return json.loads(template.render(expanded=record))["da_details"]


CHAIN = {
    "lowest_level_value_id": "kebele-ET040301888007",
    "hierarchy": [
        {"level_mnemonic": "region", "level_value_id": "region-ET04", "level_value_mnemonic": "Oromia"},
        {"level_mnemonic": "zone", "level_value_id": "zone-ET0403", "level_value_mnemonic": "Ilu Aba Bora"},
        {"level_mnemonic": "woreda", "level_value_id": "woreda-ET040301", "level_value_mnemonic": "Darimu"},
        {"level_mnemonic": "kebele", "level_value_id": "kebele-ET040301888007", "level_value_mnemonic": "Meti Guda"},
    ],
}
RECORD = {
    "functional_record_id": "DA-3500000001",
    "foundational_id": "783433844718",
    "region_name": "Oromia",
    "zone_name": "Ilu Aba Bora",
    "woreda_name": "Darimu",
    "kebele_name": "Meti Guda",
    "geo_lowest_level_value_id": "kebele-ET040301888007",
    "geo_code_hierarchy_json": CHAIN,
}


class TestLocationCodes(unittest.TestCase):
    def test_codes_come_from_the_stored_chain(self):
        posting = render(RECORD)["posting"]
        self.assertEqual(
            (posting["region_code"], posting["zone_code"], posting["woreda_code"], posting["kebele_code"]),
            ("ET04", "ET0403", "ET040301", "ET040301888007"),
        )
        self.assertEqual((posting["region"], posting["woreda"]), ("Oromia", "Darimu"))

    def test_chain_written_by_the_staff_form(self):
        # The staff form stores "level" next to "level_mnemonic".
        chain = {"hierarchy": [{"level": "woreda", "level_mnemonic": "woreda", "level_value_id": "woreda-ET010101"}]}
        posting = render(dict(RECORD, geo_code_hierarchy_json=chain))["posting"]
        self.assertEqual(posting["woreda_code"], "ET010101")
        self.assertEqual(posting["region_code"], "")

    def test_record_without_a_chain_has_empty_codes(self):
        posting = render(dict(RECORD, geo_code_hierarchy_json=None, geo_lowest_level_value_id=None))["posting"]
        self.assertEqual(
            (posting["region_code"], posting["zone_code"], posting["woreda_code"], posting["kebele_code"]),
            ("", "", "", ""),
        )


if __name__ == "__main__":
    unittest.main()
