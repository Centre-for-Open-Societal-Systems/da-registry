"""The import enrichers resolve coded values against Master Data lists
(code_lists.py): code, display or translation, case-insensitive; anything else
names the allowed displays. Imports openg2p_registry_core (container)."""

import importlib
import sys
import unittest
from unittest import mock

sys.modules.setdefault("openg2p_registry_extensions", importlib.import_module("openg2p_registry_da_extension"))
from openg2p_registry_da_extension.ingestion_pipeline.enricher_services import code_lists as cl  # noqa: E402

REG = "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90"
SCHEMA = {"widgets": [
    {"widget": "select", "widget-id": "position", "widget-label": "Position", "widget-data-path": f"{REG}.position",
     "widget-data-source": {"type": "api", "service": "attributes", "endpoint": "values", "params": {"attribute_id": "DA_POSITION"}}},
    {"widget": "input", "widget-id": "first_name", "widget-label": "Name", "widget-data-path": f"{REG}.first_name"},
]}
VALUES = {"DEVELOPMENT_AGENT": "Development Agent", "SENIOR_DA": "Senior DA", "SUPERVISOR": "Supervisor",
          "__i18n__SUPERVISOR": '{"am": "ተቆጣጣሪ"}', "__code__SUP": "SUPERVISOR"}


class TestResolve(unittest.TestCase):
    def setUp(self):
        cl.invalidate()
        session = mock.Mock()
        session.execute.return_value.scalars.return_value.all.return_value = [SCHEMA]
        self.session = session
        self.values = mock.patch.object(cl, "attribute_values", return_value=VALUES); self.values.start(); self.addCleanup(self.values.stop)
        self.addCleanup(cl.invalidate)

    def test_field_attributes_come_from_the_form_metadata(self):
        self.assertEqual(cl.field_attributes(self.session), ({"position": "DA_POSITION"}, {"position": "Position", "first_name": "Name"}))

    def test_code_display_translation_and_alternate_code_resolve(self):
        for given in ("SENIOR_DA", "senior da", "Senior DA", "senior-da"):
            self.assertEqual(cl.resolve_code("position", given, self.session), "SENIOR_DA", given)
        self.assertEqual(cl.resolve_code("position", "ተቆጣጣሪ", self.session), "SUPERVISOR")
        self.assertEqual(cl.resolve_code("position", "sup", self.session), "SUPERVISOR")
        self.assertIsNone(cl.resolve_code("position", "  ", self.session))

    def test_a_value_added_in_master_data_is_accepted_without_a_code_change(self):
        self.assertEqual(cl.resolve_code("position", "Supervisor", self.session), "SUPERVISOR")

    def test_unknown_value_lists_the_displays(self):
        with self.assertRaises(ValueError) as ctx:
            cl.resolve_code("position", "Manager", self.session)
        self.assertEqual(str(ctx.exception), "Position 'Manager' is not one of: Development Agent, Senior DA, Supervisor")

    def test_uncoded_field_passes_through(self):
        self.assertEqual(cl.resolve_code("first_name", " Abebe ", self.session), "Abebe")

    def test_read_mode(self):
        with mock.patch.dict("os.environ", {cl.ENV_PREFIX + "READ_MODE": "", cl.ENV_PREFIX + "DB_HOSTNAME": "postgres"}):
            self.assertEqual(cl._read_mode(), "db")
        with mock.patch.dict("os.environ", {cl.ENV_PREFIX + "READ_MODE": "", cl.ENV_PREFIX + "DB_HOSTNAME": ""}):
            self.assertEqual(cl._read_mode(), "api")
        with mock.patch.dict("os.environ", {cl.ENV_PREFIX + "READ_MODE": "api", cl.ENV_PREFIX + "DB_HOSTNAME": "postgres"}):
            self.assertEqual(cl._read_mode(), "api")


if __name__ == "__main__":
    unittest.main()
