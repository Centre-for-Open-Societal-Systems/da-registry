"""A dropdown value outside its Master Data list is refused with the choices.
Imports openg2p_registry_core, so it runs in the container."""

import asyncio
import time
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


def check(record, lists=LISTS, calls=None):
    def values(attribute, timeout=None):
        if calls is not None:
            calls.append((attribute, timeout))
        value = lists[attribute]
        if isinstance(value, Exception):
            raise value
        return value
    with mock.patch.object(cc.code_lists, "attribute_values", side_effect=values):
        asyncio.run(cc.validate_choices(record, SECTIONS))


class TestChoices(unittest.TestCase):
    def setUp(self):
        cc._down_until = 0.0
        self.addCleanup(setattr, cc, "_down_until", 0.0)

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

    def test_one_failure_ends_the_check_and_is_remembered(self):
        down = {"GENDER": MasterDataUnavailable("down"), "DA_POSITION": MasterDataUnavailable("down")}
        calls = []
        check({"gender": "MALE", "position": "BOSS"}, down, calls)
        self.assertEqual(len(calls), 1)  # the second dropdown was not tried
        check({"gender": "MALE", "position": "BOSS"}, down, calls)
        self.assertEqual(len(calls), 1)  # nor the next save, for a minute
        cc._down_until = time.monotonic() - 1
        check({"gender": "MALE"}, down, calls)
        self.assertEqual(len(calls), 2)

    def test_lists_are_read_with_a_short_timeout(self):
        calls = []
        check({"gender": "MALE"}, LISTS, calls)
        self.assertEqual(calls, [("GENDER", cc.TIMEOUT_SECONDS)])
        self.assertLessEqual(cc.TIMEOUT_SECONDS, 5.0)

    def test_long_lists_are_cut_after_ten_choices(self):
        many = {f"V{i}": f"Choice {i}" for i in range(13)}
        with self.assertRaises(G2PRegistryException) as ctx:
            check({"gender": "ZZZ"}, {"GENDER": many, "DA_POSITION": {}})
        message = str(ctx.exception)
        self.assertIn("Choice 9 and 3 more.", message)
        self.assertNotIn("Choice 10", message)

    def test_an_empty_list_is_not_judged(self):
        check({"position": "BOSS"}, {"GENDER": {}, "DA_POSITION": {}})
