"""A dropdown value outside its Master Data list is refused with the choices.
Imports openg2p_registry_core, so it runs in the container."""

import asyncio
import importlib
import sys
import unittest
from unittest import mock

sys.modules.setdefault("openg2p_registry_extensions", importlib.import_module("openg2p_registry_da_extension"))
from openg2p_registry_core.errors import G2PRegistryException  # noqa: E402
from openg2p_registry_da_extension.ingestion_pipeline.enricher_services.master_data_api import MasterDataUnavailable  # noqa: E402
from openg2p_registry_da_extension.register_domain.services import choice_check as cc  # noqa: E402

REG = "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90"


def select(field, label, attribute):
    return {"widget": "select", "widget-id": field, "widget-label": label, "widget-data-path": f"{REG}.{field}",
            "widget-data-source": {"type": "api", "service": "attributes", "endpoint": "values",
                                   "params": {"attribute_id": attribute}}}


SECTIONS = [("Personal details", {"panels": [{"widgets": [
    select("gender", "Gender", "GENDER"), select("position", "Position", "DA_POSITION"),
    {"widget": "text", "widget-id": "first_name", "widget-label": "Name", "widget-data-path": f"{REG}.first_name"},
]}]}, False)]
LISTS = {
    "GENDER": {"MALE": "Male", "FEMALE": "Female", "OTHER": "Other"},
    "DA_POSITION": {"DEVELOPMENT_AGENT": "Development agent", "SENIOR_DA": "Senior development agent", "__code__SDA": "SENIOR_DA"},
}


def check(record, lists=LISTS):
    def values(attribute):
        value = lists[attribute]
        if isinstance(value, Exception):
            raise value
        return value
    with mock.patch.object(cc.code_lists, "attribute_values", side_effect=values):
        asyncio.run(cc.validate_choices(record, SECTIONS))


class TestChoices(unittest.TestCase):
    def test_fields_come_from_the_widgets(self):
        self.assertEqual(cc.choice_fields(SECTIONS), {"gender": ("GENDER", "Gender"), "position": ("DA_POSITION", "Position")})

    def test_values_in_the_list_pass(self):
        check({"gender": "MALE", "position": "SENIOR_DA", "first_name": "Abebe"})
        check({"position": "SDA"})  # an alternate code of the list

    def test_absent_and_blank_values_are_not_checked(self):
        check({"first_name": "Abebe"})
        check({"gender": "", "position": None})

    def test_value_outside_the_list_names_the_choices(self):
        for record, message in [
            ({"gender": "XYZ"}, "Gender: 'XYZ' is not one of the choices. Choose one of: Male, Female, Other."),
            ({"position": "BOSS"}, "Position: 'BOSS' is not one of the choices. Choose one of: Development agent, Senior development agent."),
        ]:
            with self.subTest(record=record), self.assertRaises(G2PRegistryException) as ctx:
                check(record)
            self.assertIn(message, str(ctx.exception))

    def test_master_data_down_does_not_block_a_save(self):
        check({"gender": "XYZ"}, {"GENDER": MasterDataUnavailable("down"), "DA_POSITION": {}})

    def test_an_empty_list_is_not_judged(self):
        check({"position": "BOSS"}, {"GENDER": {}, "DA_POSITION": {}})
