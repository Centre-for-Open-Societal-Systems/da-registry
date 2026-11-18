"""Position and reporting: one position per person, and what the position decides.

- Specialisation is asked of a development agent and a senior DA only.
- "Reports to" is asked of everyone but the administrator, holds the DA-ID of
  an active person in the register, and may be left out of a file or a push.
- An education record is required of a development agent and a senior DA.
The rules are the section metadata's; the form and the API read the same ones.
"""

import asyncio
import pathlib
import re
import unittest
from types import SimpleNamespace
from unittest import mock

from openg2p_registry_da_extension.register_domain.services import g2p_register_domain_service_da as service
from openg2p_registry_da_extension.register_domain.services import required_fields as rf

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "openg2p_registry_da_extension"
DA = service.G2PRegisterDomainServiceDA
POSITION = "reg.position"


def when(action, value):
    return {"action": action, "condition": {"field": POSITION, "operator": "equals", "value": value}}


# As 85_position_and_reporting.sql and 80_qualification_list.sql define them.
PROFESSIONAL = {"panels": [{"widgets": [
    {"widget": "select", "widget-label": "Position", "widget-data-path": POSITION, "widget-required": True},
    {"widget": "select", "widget-label": "Specialisation", "widget-data-path": "reg.specialisation",
     "widget-required": True, "widget-data-options": {"actions": [when("show", "DEVELOPMENT_AGENT")]}},
    {"widget": "select", "widget-label": "Specialisation", "widget-data-path": "reg.specialisation",
     "widget-required": True, "widget-data-options": {"actions": [when("show", "SENIOR_DA")]}},
    {"widget": "date", "widget-label": "Joining date", "widget-data-path": "reg.joined_date"},
    {"widget": "oan-reports-to", "widget-label": "Reports to", "widget-data-path": "reg.reports_to",
     "widget-required": True, "oan-optional-on-import": True,
     "widget-data-options": {"actions": [when("hide", "ADMIN")]}},
]}]}
EDUCATION = {"panels": [{"widgets": [{
    "widget": "dialog-table", "widget-label": "Education", "widget-data-path": "edu.records",
    "widget-required": False,
    "widget-data-options": {"actions": [when("require", "DEVELOPMENT_AGENT"), when("require", "SENIOR_DA")]},
    "widget-data-columns": [
        {"column-key": "education_level", "widget-label": "Education Level", "widget-required": True},
        {"column-key": "passout_year", "widget-label": "Passout Year", "widget-required": True},
        {"column-key": "certificates", "widget-label": "Certificates & documents", "widget-required": False},
    ],
}]}]}
SECTIONS = [("Position and reporting", PROFESSIONAL, False), ("Education", EDUCATION, True)]


def problems(record, **kw):
    return rf.problems(PROFESSIONAL, record, absent_is_missing=True, **kw)


class SpecialisationTests(unittest.TestCase):
    def test_a_development_agent_and_a_senior_da_must_give_one(self):
        for position in ("DEVELOPMENT_AGENT", "SENIOR_DA"):
            self.assertEqual(problems({"position": position, "reports_to": "DA-1"}), ["fill in Specialisation"])
            self.assertEqual(problems({"position": position, "specialisation": "AGRONOMY", "reports_to": "DA-1"}), [])

    def test_other_positions_are_not_asked_for_one(self):
        for position in ("SUPERVISOR", "COMMUNICATION_OFFICER", "EXECUTIVE_OFFICER"):
            self.assertEqual(problems({"position": position, "reports_to": "DA-1"}), [])

    def test_a_specialisation_left_from_another_position_is_emptied(self):
        record = {"position": "SUPERVISOR", "specialisation": "AGRONOMY", "reports_to": "DA-1"}
        DA._clear_hidden_fields(record, SECTIONS)
        self.assertIsNone(record["specialisation"])
        self.assertEqual(record["reports_to"], "DA-1")

    def test_it_is_kept_for_the_positions_that_have_one(self):
        for position in ("DEVELOPMENT_AGENT", "SENIOR_DA"):
            record = {"position": position, "specialisation": "AGRONOMY"}
            DA._clear_hidden_fields(record, SECTIONS)
            self.assertEqual(record["specialisation"], "AGRONOMY")

    def test_a_change_that_does_not_name_the_position_leaves_it_alone(self):
        record = {"specialisation": "AGRONOMY", "joined_date": "2015-01-10"}
        DA._clear_hidden_fields(record, SECTIONS)
        self.assertEqual(record["specialisation"], "AGRONOMY")


class ReportsToRequirementTests(unittest.TestCase):
    def test_everyone_but_the_administrator_must_name_a_person(self):
        self.assertEqual(problems({"position": "SUPERVISOR"}), ["fill in Reports to"])
        self.assertEqual(problems({"position": "DEVELOPMENT_AGENT", "specialisation": "AGRONOMY"}),
                         ["fill in Reports to"])
        self.assertEqual(problems({"position": "ADMIN"}), [])

    def test_an_administrators_reports_to_is_emptied(self):
        record = {"position": "ADMIN", "reports_to": "DA-1"}
        DA._clear_hidden_fields(record, SECTIONS)
        self.assertIsNone(record["reports_to"])

    def test_a_file_import_and_a_push_may_leave_it_out(self):
        self.assertEqual(problems({"position": "SUPERVISOR", "source": "CSV_IMPORT"}), [])
        self.assertEqual(problems({"position": "SUPERVISOR", "source": "WEB_INTAKE", "upstream_reference": "FR-1"}),
                         [])
        self.assertIsNone(rf.incomplete_reason({"position": "SUPERVISOR", "source": "CSV_IMPORT"}, SECTIONS))

    def test_the_form_may_not(self):
        self.assertEqual(problems({"position": "SUPERVISOR", "source": "WEB_INTAKE"}), ["fill in Reports to"])
        self.assertEqual(problems({"position": "SUPERVISOR", "source": ""}), ["fill in Reports to"])


class EducationRequirementTests(unittest.TestCase):
    def test_a_development_agent_and_a_senior_da_need_a_record(self):
        for position in ("DEVELOPMENT_AGENT", "SENIOR_DA"):
            self.assertTrue(rf.list_requires_row(EDUCATION, {"position": position}))

    def test_other_positions_do_not(self):
        for position in ("SUPERVISOR", "COMMUNICATION_OFFICER", "EXECUTIVE_OFFICER", "ADMIN", "", None):
            self.assertFalse(rf.list_requires_row(EDUCATION, {"position": position}))

    def test_without_the_record_nothing_is_demanded(self):
        # The form saves Education before the position is known only if it is
        # opened out of order; the submit check, which has the record, decides.
        self.assertFalse(rf.list_requires_row(EDUCATION))
        self.assertFalse(rf.list_requires_row(EDUCATION, {}))

    def test_a_file_row_of_a_development_agent_needs_its_education(self):
        row = {"position": "DEVELOPMENT_AGENT", "specialisation": "AGRONOMY", "source": "CSV_IMPORT"}
        self.assertEqual(rf.incomplete_reason(row, SECTIONS),
                         "Required: Education: fill in Education Level, Passout Year")
        self.assertIsNone(rf.incomplete_reason({**row, "education_level": "DEGREE", "passout_year": 2010}, SECTIONS))

    def test_a_file_row_of_a_supervisor_does_not(self):
        self.assertIsNone(rf.incomplete_reason({"position": "SUPERVISOR", "source": "CSV_IMPORT"}, SECTIONS))


class _Connection:
    def __init__(self, row):
        self.row, self.asked = row, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, _statement, params=None):
        self.asked.append(params)
        return SimpleNamespace(first=lambda: self.row)


def check(record, row):
    connection = _Connection(row)
    engine = SimpleNamespace(connect=lambda: connection)
    with mock.patch("openg2p_fastapi_common.context.dbengine.get", return_value=engine):
        asyncio.run(DA._validate_reports_to(record))
    return connection


def message(raised):
    return str(getattr(raised.exception, "message", None) or getattr(raised.exception, "detail", raised.exception))


class ReportsToValueTests(unittest.TestCase):
    def test_a_record_that_does_not_name_it_is_left_alone(self):
        record = {"position": "SUPERVISOR"}
        self.assertEqual(check(record, None).asked, [])
        self.assertEqual(record, {"position": "SUPERVISOR"})

    def test_empty_is_stored_as_nothing(self):
        for value in (None, "", "  "):
            record = {"reports_to": value}
            check(record, None)
            self.assertIsNone(record["reports_to"])

    def test_the_id_of_an_active_person_is_accepted(self):
        record = {"internal_record_id": "me", "reports_to": "DA-1000000001"}
        connection = check(record, ("someone-else", "ACTIVE"))
        self.assertEqual(record["reports_to"], "DA-1000000001")
        self.assertEqual(connection.asked, [{"id": "DA-1000000001"}])

    def test_the_id_is_looked_up_as_it_was_sent(self):
        # A change request stores what was sent, so another spelling of the ID
        # is not tidied here: it finds no one and is refused.
        for sent in ("da-1000000001", " DA-1000000001 "):
            connection = _Connection(None)
            with mock.patch("openg2p_fastapi_common.context.dbengine.get",
                            return_value=SimpleNamespace(connect=lambda: connection)), self.assertRaises(Exception):
                asyncio.run(DA._validate_reports_to({"reports_to": sent}))
            self.assertEqual(connection.asked, [{"id": sent}])

    def test_an_id_no_one_has_is_refused(self):
        with self.assertRaises(Exception) as raised:
            check({"reports_to": "DA-0000000000"}, None)
        self.assertIn("no one in the register has the ID DA-0000000000", message(raised))

    def test_a_person_who_is_no_longer_active_is_refused(self):
        with self.assertRaises(Exception) as raised:
            check({"reports_to": "DA-1000000001"}, ("someone-else", "INACTIVE"))
        self.assertIn("no longer active", message(raised))

    def test_a_person_cannot_report_to_themselves(self):
        with self.assertRaises(Exception) as raised:
            check({"internal_record_id": "me", "reports_to": "DA-1000000001"}, ("me", "ACTIVE"))
        self.assertIn("cannot report to themselves", message(raised))


class MetadataTests(unittest.TestCase):
    PROFESSIONAL = (SRC / "meta_data" / "zz-oan" / "85_position_and_reporting.sql").read_text()
    EDUCATION = (SRC / "meta_data" / "zz-oan" / "80_qualification_list.sql").read_text()

    def test_specialisation_is_shown_for_the_two_da_positions(self):
        shown = re.findall(r"'action', 'show', 'condition', jsonb_build_object\(\s*'field', '[^']+\.position', "
                           r"'operator', 'equals', 'value', '(\w+)'", self.PROFESSIONAL)
        self.assertEqual(shown, ["DEVELOPMENT_AGENT", "SENIOR_DA"])

    def test_reports_to_is_hidden_for_the_administrator_and_optional_on_import(self):
        self.assertRegex(self.PROFESSIONAL, r"'action', 'hide', 'condition', jsonb_build_object\(\s*'field', "
                                            r"'[^']+\.position', 'operator', 'equals', 'value', 'ADMIN'")
        self.assertIn("'oan-optional-on-import', true", self.PROFESSIONAL)

    def test_the_education_table_is_required_for_the_two_da_positions_only(self):
        self.assertIn("'widget-label', 'Education', 'widget-readonly', false, 'widget-required', false", self.EDUCATION)
        required = re.findall(r"'action', 'require', 'condition', jsonb_build_object\(\s*'field', "
                              r"'[^']+\.position', 'operator', 'equals', 'value', '(\w+)'", self.EDUCATION)
        self.assertEqual(required, ["DEVELOPMENT_AGENT", "SENIOR_DA"])

    def test_an_education_record_has_no_position_specialisation_or_joining_date(self):
        for column in ("specialisation", "position", "joined_date"):
            self.assertNotIn(f"'column-key','{column}'", self.EDUCATION)

    def test_no_label_staff_read_uses_the_shorthand_da(self):
        # 30_readable_text_checks.sql refuses it when the metadata is seeded.
        for text in re.findall(r"'(?:widget-label|panel-title|section-title)', '([^']+)'", self.PROFESSIONAL):
            self.assertNotRegex(text, r"\bDA\b", text)

    def test_the_person_reported_to_sits_beside_the_position_not_under_it(self):
        left, right = self.PROFESSIONAL.split("AS position_panel")
        for widget in ("'position'", "'specialisation'", "'joined_date'"):
            self.assertIn(f"'widget-id', {widget}", left)
        self.assertIn("'widget-id', 'reports_to'", right)
        self.assertIn("jsonb_build_array(parts.position_panel, parts.reports_to_panel)", right)

    def test_professional_details_comes_before_education_on_the_form(self):
        order = int(re.search(r"'da_intake_section_service'[^)]*,(\d+)\)", self.PROFESSIONAL).group(1))
        education = int(re.search(r"'da_intake_section_qualification'[^)]*,(\d+)\)", self.EDUCATION).group(1))
        self.assertLess(order, education)


if __name__ == "__main__":
    unittest.main()
