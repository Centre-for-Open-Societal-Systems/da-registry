"""Work location: required of everyone but the administrator (18 Nov 2026).

The rule is a "require" action on the location widget whose condition reads
the position, a field of another section. The checks give it the rest of the
record: the form's section save and submit, the API's check (from the stored
record), and the import and push (the whole record).
"""

import pathlib
import re
import unittest

from openg2p_registry_da_extension.register_domain.services import required_fields as rf
from openg2p_registry_da_extension.register_domain.services.g2p_register_domain_service_da import (
    G2PRegisterDomainServiceDA as Service,
)

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "openg2p_registry_da_extension"
LOCATION = {"panels": [{"panels": [{"widgets": [{
    "widget": "geo-hierarchy", "widget-label": "Region, zone, woreda and kebele", "widget-required": False,
    "widget-data-path": {"value": "reg.geo_lowest_level_value_id", "hierarchy": "reg.geo_code_hierarchy_json"},
    "widget-data-options": {"actions": [{"action": "require", "condition": {
        "field": "reg.position", "operator": "notEquals", "value": "ADMIN"}}]},
}]}]}]}
POSITION = {"panels": [{"widgets": [
    {"widget": "select", "widget-label": "Position", "widget-required": True, "widget-data-path": "reg.position"}]}]}
SECTIONS = [("Position and reporting", POSITION, False), ("Work location", LOCATION, False)]
NO_PLACE = {"geo_lowest_level_value_id": None, "geo_code_hierarchy_json": None}
PLACE = {"geo_lowest_level_value_id": "kebele-1", "geo_code_hierarchy_json": {"hierarchy": []}}


def location_problems(record):
    return rf.problems(LOCATION, record, absent_is_missing=True)


class RuleTests(unittest.TestCase):
    def test_everyone_but_the_administrator_must_give_a_work_location(self):
        for position in ("DEVELOPMENT_AGENT", "SENIOR_DA", "SUPERVISOR", "COMMUNICATION_OFFICER", "EXECUTIVE_OFFICER"):
            self.assertEqual(location_problems({"position": position, **NO_PLACE}),
                             ["fill in Region, zone, woreda and kebele"], position)

    def test_the_administrator_may_leave_it_empty_or_give_one(self):
        self.assertEqual(location_problems({"position": "ADMIN", **NO_PLACE}), [])
        self.assertEqual(location_problems({"position": "ADMIN", **PLACE}), [])

    def test_without_a_position_it_stays_required(self):
        self.assertEqual(location_problems(NO_PLACE), ["fill in Region, zone, woreda and kebele"])

    def test_the_condition_reads_the_position(self):
        self.assertEqual(rf.condition_fields(LOCATION), ["position"])


class ImportTests(unittest.TestCase):
    def test_a_file_row_or_push_of_an_administrator_may_come_without_a_location(self):
        self.assertIsNone(rf.incomplete_reason({"position": "ADMIN", "source": "CSV_IMPORT", **NO_PLACE}, SECTIONS))

    def test_anyone_else_without_a_location_is_refused(self):
        self.assertEqual(rf.incomplete_reason({"position": "SUPERVISOR", "source": "CSV_IMPORT", **NO_PLACE}, SECTIONS),
                         "Required: Work location: fill in Region, zone, woreda and kebele")

    def test_a_row_naming_some_of_the_four_places_is_refused(self):
        from openg2p_registry_da_extension.ingestion_pipeline.enricher_services.g2p_da_enricher_services import (
            _geo_from_names,
        )

        self.assertIsNone(_geo_from_names({"region": "", "zone": None}))
        with self.assertRaises(ValueError) as raised:
            _geo_from_names({"region": "Tigray", "zone": "North Western"})
        self.assertEqual(str(raised.exception), "Missing: Woreda, Kebele")


class ApiCheckTests(unittest.TestCase):
    """A change of the Work location alone does not carry the position; the
    API's check is given the stored one."""

    def check(self, record, context):
        Service._validate_required({"source": "WEB_INTAKE", **record}, SECTIONS, context)

    def test_an_administrator_may_clear_their_work_location(self):
        self.check(dict(NO_PLACE), {"position": "ADMIN"})

    def test_anyone_else_may_not(self):
        with self.assertRaises(Exception) as raised:
            self.check(dict(NO_PLACE), {"position": "SUPERVISOR"})
        self.assertIn("Work location: fill in Region, zone, woreda and kebele",
                      str(getattr(raised.exception, "message", None) or raised.exception))

    def test_a_position_in_the_change_itself_wins_over_the_stored_one(self):
        with self.assertRaises(Exception):
            self.check({"position": "SUPERVISOR", **NO_PLACE}, {"position": "ADMIN"})

    def test_a_change_of_another_field_is_not_asked_for_the_location(self):
        self.check({"email": "a@example.org"}, {"position": "SUPERVISOR"})

    def test_an_empty_stored_value_is_not_taken_for_a_blanked_field(self):
        # A draft whose position is not saved yet: saving the contact section
        # must not be refused with "fill in Position".
        self.check({"email": "a@example.org"}, {"position": None})


class MetadataTests(unittest.TestCase):
    SQL = (SRC / "meta_data" / "zz-oan" / "95_work_location.sql").read_text()

    def test_the_location_is_required_unless_the_position_is_admin(self):
        self.assertIn("'{panels,0,panels,0,widgets,0,widget-required}', 'false'::jsonb", self.SQL)
        self.assertRegex(self.SQL, r"'action', 'require', 'condition', jsonb_build_object\(\s*'field', "
                                   r"'[^']+\.position', 'operator', 'notEquals', 'value', 'ADMIN'")


if __name__ == "__main__":
    unittest.main()
