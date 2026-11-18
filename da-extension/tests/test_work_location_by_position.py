"""Work location by position (18 Nov 2026, location_depth.py).

Development agent, Senior DA: Region to Kebele. Supervisor, Executive officer:
Region to Woreda. Admin, Communication officer: no Work location. One key on
the geo widget, "oan-location-depth", read by the form's checks, the API, a
file import and a DA Services push. What goes deeper than the position's level
is left out, not refused.
"""

import asyncio
import json
import pathlib
import unittest
from types import SimpleNamespace
from unittest import mock

from openg2p_registry_da_extension.ingestion_pipeline.enricher_services import g2p_da_enricher_services as module
from openg2p_registry_da_extension.register_domain.services import location_depth as ld
from openg2p_registry_da_extension.register_domain.services import required_fields as rf
from openg2p_registry_da_extension.register_domain.services.g2p_register_domain_service_da import (
    G2PRegisterDomainServiceDA as Service,
)

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "openg2p_registry_da_extension"
RULE = {
    "field": "reg.position",
    "levels": {"DEVELOPMENT_AGENT": "kebele", "SENIOR_DA": "kebele", "SUPERVISOR": "woreda",
               "EXECUTIVE_OFFICER": "woreda", "ADMIN": "none", "COMMUNICATION_OFFICER": "none"},
    "default": "kebele",
}
LOCATION = {"panels": [{"panels": [{"widgets": [{
    "widget": "geo-hierarchy", "widget-id": "da_geo_hierarchy", "widget-label": "Region, zone, woreda and kebele",
    "widget-required": False, "widget-data-options": {},
    "widget-data-path": {"value": "reg.geo_lowest_level_value_id", "hierarchy": "reg.geo_code_hierarchy_json"},
    "oan-location-depth": RULE,
}]}]}]}
POSITION = {"panels": [{"widgets": [
    {"widget": "select", "widget-label": "Position", "widget-required": True, "widget-data-path": "reg.position"}]}]}
SECTIONS = [("Position and reporting", POSITION, False), ("Work location", LOCATION, False)]
NO_PLACE = {"geo_lowest_level_value_id": None, "geo_code_hierarchy_json": None}


def entry(level, value_id, name):
    return {"level": level, "level_id": f"level-{level}", "level_mnemonic": level,
            "level_value_id": value_id, "level_value_mnemonic": name}


CHAIN = {"hierarchy": [entry("country", "ET", "Ethiopia"), entry("region", "ET01", "Tigray"),
                       entry("zone", "ET0101", "North Western"), entry("woreda", "ET010101", "Tahtay Adiyabo"),
                       entry("kebele", "ET01010101", "Adi Hageray")],
         "lowest_level_value_id": "ET01010101"}
TO_WOREDA = {**CHAIN, "hierarchy": CHAIN["hierarchy"][:4], "lowest_level_value_id": "ET010101"}
TO_ZONE = {**CHAIN, "hierarchy": CHAIN["hierarchy"][:3], "lowest_level_value_id": "ET0101"}
PLACE = {"geo_lowest_level_value_id": "ET01010101", "geo_code_hierarchy_json": CHAIN}


class RuleTests(unittest.TestCase):
    def test_level_per_position(self):
        for position, level in (("DEVELOPMENT_AGENT", "kebele"), ("SENIOR_DA", "kebele"), ("SUPERVISOR", "woreda"),
                                ("EXECUTIVE_OFFICER", "woreda"), ("ADMIN", "none"),
                                ("COMMUNICATION_OFFICER", "none"), ("", "kebele"), ("NEW_POSITION", "kebele")):
            self.assertEqual(ld.depth_for(RULE, {"position": position}), level, position)

    def test_required_of_everyone_with_a_location(self):
        for position in ("DEVELOPMENT_AGENT", "SENIOR_DA", "SUPERVISOR", "EXECUTIVE_OFFICER"):
            self.assertEqual(rf.problems(LOCATION, {"position": position, **NO_PLACE}, absent_is_missing=True),
                             ["fill in Region, zone, woreda and kebele"], position)
        # A record whose position is not known yet: still required.
        self.assertEqual(rf.problems(LOCATION, dict(NO_PLACE), absent_is_missing=True),
                         ["fill in Region, zone, woreda and kebele"])

    def test_hidden_and_not_required_without_a_location(self):
        for position in ("ADMIN", "COMMUNICATION_OFFICER"):
            self.assertEqual(rf.problems(LOCATION, {"position": position, **NO_PLACE}, absent_is_missing=True), [])
            self.assertEqual(rf.hidden_fields(LOCATION, {"position": position, **PLACE}),
                             ["geo_lowest_level_value_id", "geo_code_hierarchy_json"])
        self.assertEqual(rf.hidden_fields(LOCATION, {"position": "SUPERVISOR", **PLACE}), [])

    def test_the_conditions_read_the_position(self):
        self.assertEqual(rf.condition_fields(LOCATION), ["position"])
        self.assertTrue(rf.has_requirements(LOCATION))

    def test_cut_back_to_the_level(self):
        self.assertEqual(ld.cut(CHAIN, "woreda"), TO_WOREDA)
        self.assertIs(ld.cut(CHAIN, "kebele"), CHAIN)
        self.assertIsNone(ld.cut(TO_WOREDA, "kebele"))


class FitRecordTests(unittest.TestCase):
    def fit(self, record, context=None):
        return ld.fit_record(record, RULE, context), record

    def test_a_kebele_for_a_supervisor_is_left_out(self):
        problem, record = self.fit({"position": "SUPERVISOR", **PLACE})
        self.assertIsNone(problem)
        self.assertEqual(record["geo_lowest_level_value_id"], "ET010101")
        self.assertEqual(record["geo_code_hierarchy_json"], TO_WOREDA)

    def test_the_position_may_come_from_the_stored_record(self):
        problem, record = self.fit(dict(PLACE), {"position": "EXECUTIVE_OFFICER"})
        self.assertIsNone(problem)
        self.assertEqual(record["geo_lowest_level_value_id"], "ET010101")

    def test_no_location_for_an_administrator_or_a_communication_officer(self):
        for position in ("ADMIN", "COMMUNICATION_OFFICER"):
            problem, record = self.fit({"position": position, **PLACE})
            self.assertIsNone(problem)
            self.assertEqual((record["geo_lowest_level_value_id"], record["geo_code_hierarchy_json"]), (None, None))

    def test_a_location_above_the_level_is_refused(self):
        problem, _ = self.fit({"position": "DEVELOPMENT_AGENT", "geo_lowest_level_value_id": "ET010101",
                               "geo_code_hierarchy_json": TO_WOREDA})
        self.assertEqual(problem, "Work location: choose the Kebele")
        problem, _ = self.fit({"position": "SUPERVISOR", "geo_lowest_level_value_id": "ET0101",
                               "geo_code_hierarchy_json": json.dumps(TO_ZONE)})
        self.assertEqual(problem, "Work location: choose the Woreda")

    def test_left_alone_when_nothing_says_the_position_or_no_location_is_sent(self):
        problem, record = self.fit(dict(PLACE))
        self.assertIsNone(problem)
        self.assertEqual(record, PLACE)
        self.assertEqual(self.fit({"position": "SUPERVISOR", "email": "a@example.org"}),
                         (None, {"position": "SUPERVISOR", "email": "a@example.org"}))

    def test_the_api_refuses_a_location_above_the_level(self):
        with self.assertRaises(Exception) as raised:
            Service._fit_location({"geo_lowest_level_value_id": "ET010101", "geo_code_hierarchy_json": TO_WOREDA},
                                  SECTIONS, {"position": "DEVELOPMENT_AGENT"})
        self.assertIn("Work location: choose the Kebele", str(getattr(raised.exception, "message", None) or raised.exception))

    def test_the_api_clears_the_location_of_a_communication_officer(self):
        record = {"source": "WEB_INTAKE", **PLACE}
        Service._clear_hidden_fields(record, SECTIONS, {"position": "COMMUNICATION_OFFICER"})
        self.assertEqual((record["geo_lowest_level_value_id"], record["geo_code_hierarchy_json"]), (None, None))


LISTS = {"DA_POSITION": {"DEVELOPMENT_AGENT": "Development Agent", "SENIOR_DA": "Senior DA",
                         "SUPERVISOR": "Supervisor", "EXECUTIVE_OFFICER": "Executive officer",
                         "ADMIN": "Admin", "COMMUNICATION_OFFICER": "Communication officer"}}
ROW = {"Name": "Abebe", "Father's Name": "Kebede", "Fayda ID": "412345678901", "Position": "Supervisor",
       "Region": "Tigray", "Zone": "North Western", "Woreda": "Tahtay Adiyabo", "Kebele": "Adi Hageray"}


class ImportAndPushTests(unittest.TestCase):
    def setUp(self):
        rf.set_sections_for_tests(rf.DA_REGISTER_ID, SECTIONS)
        self.addCleanup(rf.set_sections_for_tests, rf.DA_REGISTER_ID, None)
        for target, kwargs in (
            ("field_attributes", {"return_value": ({"position": "DA_POSITION"}, {"position": "Position"})}),
            ("attribute_values", {"side_effect": lambda a: LISTS[a]}),
        ):
            patcher = mock.patch.object(module.code_lists, target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        by_name = mock.patch.object(module._MasterDataGeo, "resolve", side_effect=self.resolved)
        by_id = mock.patch.object(module._MasterDataGeo, "resolve_by_id", return_value=CHAIN)
        self.resolve, self.resolve_by_id = by_name.start(), by_id.start()
        self.addCleanup(by_name.stop)
        self.addCleanup(by_id.stop)
        self.load = mock.patch.object(module, "load_sections_sync", return_value=SECTIONS)
        self.load.start()
        self.addCleanup(self.load.stop)

    @staticmethod
    def resolved(names, levels):
        return {"hierarchy": CHAIN["hierarchy"][: 1 + len(levels)],
                "lowest_level_value_id": CHAIN["hierarchy"][len(levels)]["level_value_id"]}

    def row(self, **changes):
        return module.DAImportFileEnricherService().enrich({**ROW, **changes}, session=None)

    def push(self, **da):
        message = {"reference_id": "ref-1", "da": {"first_name": "Abebe", "father_name": "Kebede",
                                                  "fayda_id": "412345678901", **da}}
        return module.DAServicesEnricherService().enrich(message, session=None)

    def test_a_supervisor_row_goes_down_to_the_woreda_and_its_kebele_is_left_out(self):
        out = self.row()
        self.resolve.assert_called_once_with(
            {"region": "Tigray", "zone": "North Western", "woreda": "Tahtay Adiyabo"}, ("region", "zone", "woreda"))
        self.assertEqual(out["geo_lowest_level_value_id"], "ET010101")
        self.assertEqual((out["woreda_name"], out["kebele_name"]), ("Tahtay Adiyabo", None))
        self.assertEqual((out["woreda_code"], out["kebele_code"]), ("ET010101", None))

    def test_a_supervisor_row_needs_no_kebele_column(self):
        out = self.row(Kebele="", Position="Executive officer")
        self.assertEqual(out["geo_lowest_level_value_id"], "ET010101")

    def test_a_supervisor_row_without_the_woreda_is_refused(self):
        with self.assertRaisesRegex(ValueError, "^Missing: Woreda$"):
            self.row(Woreda="")

    def test_an_administrator_row_keeps_no_location_whatever_it_fills_in(self):
        for position in ("Admin", "Communication officer"):
            out = self.row(Position=position)
            self.assertIsNone(out["geo_lowest_level_value_id"])
            self.assertIsNone(out["region_name"])
        self.resolve.assert_not_called()

    def test_a_development_agent_row_needs_all_four(self):
        out = self.row(Position="Development Agent")
        self.assertEqual(out["geo_lowest_level_value_id"], "ET01010101")
        with self.assertRaisesRegex(ValueError, "^Missing: Kebele$"):
            self.row(Position="Development Agent", Kebele="")
        with self.assertRaisesRegex(ValueError, "^Missing: Region, Zone, Woreda, Kebele$"):
            self.row(Position="Development Agent", Region="", Zone="", Woreda="", Kebele="")

    def test_a_push_for_a_supervisor_with_a_kebele_id_is_cut_back_to_the_woreda(self):
        out = self.push(position="SUPERVISOR", kebele_id="ET01010101")
        self.assertEqual(out["geo_lowest_level_value_id"], "ET010101")
        self.assertEqual(out["geo_code_hierarchy_json"], TO_WOREDA)

    def test_a_push_for_a_supervisor_by_names_needs_no_kebele(self):
        out = self.push(position="SUPERVISOR", region="Tigray", zone="North Western", woreda="Tahtay Adiyabo")
        self.assertEqual(out["geo_lowest_level_value_id"], "ET010101")
        with self.assertRaisesRegex(ValueError, "Missing: region, zone, woreda"):
            self.push(position="SUPERVISOR", region="Tigray")

    def test_a_push_for_an_administrator_keeps_no_location(self):
        out = self.push(position="COMMUNICATION_OFFICER", kebele_id="ET01010101")
        self.assertIsNone(out["geo_lowest_level_value_id"])
        self.resolve_by_id.assert_not_called()

    def test_a_push_for_a_development_agent_without_a_location_is_refused(self):
        with self.assertRaisesRegex(ValueError, r"Missing: kebele_id \(or region, zone, woreda, kebele\)"):
            self.push(position="DEVELOPMENT_AGENT")


class Session:
    def __init__(self, row):
        self.row, self.updates = row, []

    async def execute(self, statement, params=None):
        sql = str(statement)
        if sql.lstrip().startswith("SELECT"):
            return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: self.row))
        self.updates.append((sql, params))


class AfterChangeTests(unittest.TestCase):
    def run_fit(self, row):
        session = Session(row)
        service = Service.__new__(Service)
        with mock.patch("openg2p_registry_da_extension.register_domain.services.g2p_register_domain_service_da"
                        ".load_sections", mock.AsyncMock(return_value=SECTIONS)):
            asyncio.run(service._fit_location_after_change("rec-1", session))
        return session.updates

    def test_a_development_agent_made_a_supervisor_keeps_the_woreda(self):
        (sql, params), = self.run_fit({"position": "SUPERVISOR", **PLACE})
        self.assertIn('"geo_lowest_level_value_id" = :lowest', sql)
        self.assertEqual(params["lowest"], "ET010101")
        self.assertEqual(json.loads(params["chain"]), TO_WOREDA)

    def test_nothing_to_do(self):
        self.assertEqual(self.run_fit({"position": "DEVELOPMENT_AGENT", **PLACE}), [])
        self.assertEqual(self.run_fit({"position": "SUPERVISOR", "geo_lowest_level_value_id": "ET010101",
                                       "geo_code_hierarchy_json": TO_WOREDA}), [])
        self.assertEqual(self.run_fit({"position": "ADMIN", **NO_PLACE}), [])
        self.assertEqual(self.run_fit(None), [])


class StoredSubmissionTests(unittest.TestCase):
    """A change of position on the form reaches the Work location already saved
    in the submission (required_fields_mixin._fit_stored_location)."""

    def test_columns_for_a_supervisor(self):
        cols = ld.fitted_columns({"position": "SUPERVISOR", **PLACE}, RULE)
        self.assertEqual(cols["geo_lowest_level_value_id"], "ET010101")
        self.assertEqual(cols["geo_code_hierarchy_json"], TO_WOREDA)
        self.assertEqual((cols["woreda_name"], cols["kebele_name"]), ("Tahtay Adiyabo", None))
        self.assertEqual((cols["woreda_code"], cols["kebele_code"]), ("ET010101", None))

    def test_columns_for_an_administrator(self):
        cols = ld.fitted_columns({"position": "ADMIN", **PLACE}, RULE)
        self.assertTrue(cols)
        self.assertTrue(all(value is None for value in cols.values()))

    def test_nothing_when_it_fits(self):
        self.assertEqual(ld.fitted_columns({"position": "DEVELOPMENT_AGENT", **PLACE}, RULE), {})
        self.assertEqual(ld.fitted_columns({"position": "ADMIN", **NO_PLACE}, RULE), {})

    def test_saving_the_position_fits_the_saved_location(self):
        from openg2p_registry_da_extension.register_domain.services import required_fields_mixin as rfm

        row = SimpleNamespace(position="SUPERVISOR", geo_lowest_level_value_id="ET01010101",
                              geo_code_hierarchy_json=CHAIN, region_name="Tigray", zone_name="North Western",
                              woreda_name="Tahtay Adiyabo", kebele_name="Adi Hageray", region_code="ET01",
                              zone_code="ET0101", woreda_code="ET010101", kebele_code="ET01010101")

        class Base:
            async def save_intake_form_submission_with_session(self, *args, **kwargs):
                return SimpleNamespace(submission_id="sub-1")

        class Intake(rfm.RequiredFieldsMixin, Base):
            async def _get_section_or_error(self, section_id, session):
                return SimpleNamespace(section_ui_schema=POSITION, is_list=False, section_mnemonic="da_service")

            async def _existing_record_ids(self, *args):
                return {"rec-1"}

            def _records_for_validation(self, payload):
                return payload

            async def _get_submission_or_error(self, submission_id, session):
                return SimpleNamespace(submission_id=submission_id, form_id="form")

            async def _resolve_intake_form_class(self, register_id, session):
                return object

            async def _get_intake_rows(self, intake_class, submission_id, session):
                return {"rec-1": row}

        session = SimpleNamespace(flush=mock.AsyncMock())
        payload = [{"internal_record_id": "rec-1", "edit_action": "UPDATE", "position": "SUPERVISOR",
                    "source": "WEB_INTAKE"}]
        with mock.patch.object(rfm, "load_sections", mock.AsyncMock(return_value=SECTIONS)), \
                mock.patch.object(rfm, "problems", return_value=[]):
            asyncio.run(Intake().save_intake_form_submission_with_session(
                "sub-1", "da_service_section_02", payload, rf.DA_REGISTER_ID, "form", rf.DA_REGISTER_ID,
                "user", session))
        self.assertEqual(row.geo_lowest_level_value_id, "ET010101")
        self.assertEqual((row.kebele_name, row.kebele_code), (None, None))
        session.flush.assert_awaited()


class MetadataTests(unittest.TestCase):
    SQL = (SRC / "meta_data" / "zz-oan" / "95_work_location.sql").read_text()

    def test_the_rule_is_in_the_metadata(self):
        self.assertIn("'{panels,0,panels,0,widgets,0,widget-required}', 'false'::jsonb", self.SQL)
        self.assertIn("'{panels,0,panels,0,widgets,0,widget-data-options}', '{}'::jsonb", self.SQL)
        self.assertIn("'{panels,0,panels,0,widgets,0,oan-location-depth}'", self.SQL)
        for pair in ("'DEVELOPMENT_AGENT', 'kebele'", "'SENIOR_DA', 'kebele'", "'SUPERVISOR', 'woreda'",
                     "'EXECUTIVE_OFFICER', 'woreda'", "'ADMIN', 'none'", "'COMMUNICATION_OFFICER', 'none'",
                     "'default', 'kebele'"):
            self.assertIn(pair, self.SQL)


if __name__ == "__main__":
    unittest.main()
