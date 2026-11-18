"""Who may give a position, and who may change it (position_rights.py).

A position decides the rights of the person's Keycloak account, so a
supervisor must not be able to register an administrator, a development agent
must not be able to change their own position, and a file or DA Services must
not bring in anyone above a development agent.
"""

import asyncio
import pathlib
import unittest
from types import SimpleNamespace
from unittest import mock

from openg2p_registry_da_extension.register_domain.services import position_rights as pr

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "openg2p_registry_da_extension"
CHANGE = ["Intake Officer", "Data Supervisor", "Operations Administrator"]
SECTION = {"panels": [{"widgets": [
    {"widget": "oan-select-by-right", "widget-label": "Position", "widget-data-path": "reg.position",
     "oan-value-rights": {"open": ["DEVELOPMENT_AGENT", "SENIOR_DA"], "roles": ["Operations Administrator"],
                          "permission": "incomingMessage:view"},
     "oan-change-roles": CHANGE},
    {"widget": "oan-reports-to", "widget-label": "Reports to (ID)", "widget-data-path": "reg.reports_to",
     "oan-change-roles": CHANGE},
    {"widget": "date", "widget-label": "Joining date", "widget-data-path": "reg.joined_date"},
]}]}
SECTIONS = [("Position and reporting", SECTION, False)]
RULES = pr.field_rules(SECTIONS)
SUPERVISOR = {"Intake Officer", "Data Editor", "Data Supervisor"}
ADMINISTRATOR = SUPERVISOR | {"Operations Administrator"}
AGENT = {"Data Editor"}


def problem(record, roles, stored=None):
    return pr.request_problem(record, RULES, roles, stored)


class RuleReadingTests(unittest.TestCase):
    def test_the_rules_are_read_from_the_widgets(self):
        self.assertEqual(sorted(RULES), ["position", "reports_to"])
        self.assertEqual(RULES["position"]["open"], {"DEVELOPMENT_AGENT", "SENIOR_DA"})
        self.assertEqual(RULES["position"]["roles"], {"Operations Administrator"})
        self.assertIsNone(RULES["reports_to"]["open"])
        self.assertEqual(RULES["reports_to"]["change_roles"], set(CHANGE))

    def test_a_section_without_rules_has_none(self):
        self.assertEqual(pr.field_rules([("x", {"panels": [{"widgets": [
            {"widget": "text", "widget-data-path": "reg.email"}]}]}, False)]), {})


class NewRecordTests(unittest.TestCase):
    def test_a_supervisor_registers_development_agents(self):
        for position in ("DEVELOPMENT_AGENT", "SENIOR_DA"):
            self.assertIsNone(problem({"position": position, "reports_to": "DA-1"}, SUPERVISOR))

    def test_a_supervisor_cannot_register_anyone_above_that(self):
        for position in ("SUPERVISOR", "COMMUNICATION_OFFICER", "EXECUTIVE_OFFICER", "ADMIN"):
            message = problem({"position": position}, SUPERVISOR)
            self.assertIn("only an administrator can give this position", message, position)
            self.assertIn(position, message)

    def test_an_administrator_registers_anyone(self):
        for position in ("DEVELOPMENT_AGENT", "SUPERVISOR", "EXECUTIVE_OFFICER", "ADMIN"):
            self.assertIsNone(problem({"position": position}, ADMINISTRATOR))

    def test_a_user_whose_roles_cannot_be_read_can_give_only_the_open_positions(self):
        self.assertIsNone(problem({"position": "DEVELOPMENT_AGENT"}, set()))
        self.assertIsNotNone(problem({"position": "ADMIN"}, set()))

    def test_an_empty_position_is_the_required_checks_business(self):
        self.assertIsNone(problem({"position": ""}, SUPERVISOR))


class ChangeTests(unittest.TestCase):
    STORED = {"position": "DEVELOPMENT_AGENT", "reports_to": "DA-1"}

    def test_a_development_agent_cannot_change_their_position_or_who_they_report_to(self):
        self.assertIn("Position: you cannot change this", problem({"position": "SENIOR_DA"}, AGENT, self.STORED))
        self.assertIn("Reports to (ID): you cannot change this",
                      problem({"reports_to": "DA-2"}, AGENT, self.STORED))

    def test_a_field_sent_as_it_is_is_not_a_change(self):
        # The form sends the whole section: an agent changing their joining date
        # sends the position and the person they report to unchanged.
        record = {"position": "DEVELOPMENT_AGENT", "reports_to": "DA-1", "joined_date": "2016-01-01"}
        self.assertIsNone(problem(record, AGENT, self.STORED))

    def test_a_supervisor_changes_who_an_agent_reports_to_and_between_the_open_positions(self):
        self.assertIsNone(problem({"reports_to": "DA-2"}, SUPERVISOR, self.STORED))
        self.assertIsNone(problem({"position": "SENIOR_DA"}, SUPERVISOR, self.STORED))

    def test_a_supervisor_cannot_promote_an_agent_above_that(self):
        self.assertIn("only an administrator", problem({"position": "ADMIN"}, SUPERVISOR, self.STORED))

    def test_a_supervisor_can_still_correct_another_field_of_an_administrators_record(self):
        stored = {"position": "ADMIN", "reports_to": None}
        self.assertIsNone(problem({"position": "ADMIN", "reports_to": "", "joined_date": "2016-01-01"},
                                  SUPERVISOR, stored))

    def test_an_administrator_changes_anything(self):
        self.assertIsNone(problem({"position": "ADMIN", "reports_to": None}, ADMINISTRATOR, self.STORED))


class ImportTests(unittest.TestCase):
    def test_a_file_or_da_services_brings_development_agents_only(self):
        self.assertIsNone(pr.import_problem({"position": "DEVELOPMENT_AGENT"}, SECTIONS))
        self.assertIsNone(pr.import_problem({"position": "SENIOR_DA", "reports_to": "DA-1"}, SECTIONS))
        for position in ("SUPERVISOR", "ADMIN"):
            message = pr.import_problem({"position": position}, SECTIONS)
            self.assertIn(f"Position: {position} cannot be given in a file import or by DA Services", message)

    def test_a_record_without_a_position_is_the_required_checks_business(self):
        self.assertIsNone(pr.import_problem({}, SECTIONS))


def run_check(record, roles, stored=None, target=None):
    """position_rights.check with the caller's roles; inside a change request
    for `target`, whose registered values are `stored`."""
    lookup = mock.AsyncMock(return_value=stored)
    token = pr._change_target.set(target)
    try:
        with mock.patch.object(pr, "caller_roles", return_value=roles), mock.patch.object(pr, "_stored", lookup):
            asyncio.run(pr.check(record, SECTIONS))
    finally:
        pr._change_target.reset(token)
    return lookup


def refused(record, roles, stored=None, target=None):
    try:
        run_check(record, roles, stored, target)
    except Exception as error:  # noqa: BLE001 - the platform's validation error
        return str(getattr(error, "message", None) or getattr(error, "detail", error))
    return None


class CheckTests(unittest.TestCase):
    def test_a_record_that_names_no_ruled_field_is_not_looked_up(self):
        with mock.patch.object(pr, "caller_roles") as roles:
            asyncio.run(pr.check({"mobile_number": "0911234567"}, SECTIONS))
        roles.assert_not_called()

    def test_through_the_staff_api_the_callers_roles_decide(self):
        self.assertIsNone(refused({"position": "ADMIN"}, ADMINISTRATOR))
        self.assertIn("only an administrator", refused({"position": "ADMIN"}, SUPERVISOR))

    def test_a_file_row_and_a_push_are_refused_above_a_development_agent(self):
        self.assertIn("file import or by DA Services", refused({"position": "ADMIN", "source": "CSV_IMPORT"}, None))
        self.assertIn("file import or by DA Services",
                      refused({"position": "SUPERVISOR", "source": "WEB_INTAKE", "upstream_reference": "FR-1"}, None))

    def test_an_approved_submission_on_its_way_to_the_register_is_not_checked_again(self):
        # The worker has no caller; the record came from the form and was checked when it was saved.
        self.assertIsNone(refused({"position": "ADMIN", "source": "WEB_INTAKE"}, None))


class ChangeTargetTests(unittest.TestCase):
    """The platform applies a payload row to the record the request is for,
    whatever id the row names. These are the requests that got round the rules
    when the row's own id was trusted."""
    AGENT_RECORD = {"position": "DEVELOPMENT_AGENT", "reports_to": "DA-1"}

    def test_the_record_compared_with_is_the_requests_not_the_one_a_row_names(self):
        lookup = run_check({"internal_record_id": "another-record", "position": "DEVELOPMENT_AGENT"},
                           AGENT, self.AGENT_RECORD, target="my-record")
        self.assertEqual(lookup.await_args.args[0], "my-record")

    def test_an_agent_cannot_change_their_position_by_leaving_the_row_id_out(self):
        self.assertIn("you cannot change this",
                      refused({"position": "SENIOR_DA"}, AGENT, self.AGENT_RECORD, target="my-record"))

    def test_nor_by_naming_a_record_that_already_has_the_position(self):
        record = {"internal_record_id": "a-senior-da", "position": "SENIOR_DA"}
        self.assertIn("you cannot change this", refused(record, AGENT, self.AGENT_RECORD, target="my-record"))

    def test_a_supervisor_cannot_promote_by_naming_a_supervisors_record(self):
        record = {"internal_record_id": "a-supervisor", "position": "SUPERVISOR"}
        self.assertIn("only an administrator", refused(record, SUPERVISOR, self.AGENT_RECORD, target="my-record"))

    def test_a_change_request_for_a_record_that_is_not_registered_is_still_a_change(self):
        # Nothing to compare with: an agent may not set the field at all.
        self.assertIn("you cannot change this", refused({"position": "SENIOR_DA"}, AGENT, None, target="unknown"))

    def test_on_a_form_save_nothing_passes_as_unchanged(self):
        # No change request: a row naming an administrator's record does not make ADMIN "as it is".
        lookup = mock.AsyncMock(return_value={"position": "ADMIN"})
        with mock.patch.object(pr, "caller_roles", return_value=SUPERVISOR), mock.patch.object(pr, "_stored", lookup):
            with self.assertRaises(Exception):
                asyncio.run(pr.check({"internal_record_id": "an-admin", "position": "ADMIN"}, SECTIONS))
        lookup.assert_not_awaited()

    def test_the_mixin_keeps_the_target_only_while_the_request_is_created(self):
        seen = []

        class Platform:
            async def create_change_request(self, payload, *args, **kwargs):
                seen.append(pr._change_target.get())
                return "created"

        class Service(pr.ChangeTargetMixin, Platform):
            pass

        payload = SimpleNamespace(internal_record_id="my-record")
        self.assertEqual(asyncio.run(Service().create_change_request(payload)), "created")
        self.assertEqual(seen, ["my-record"])
        self.assertIsNone(pr._change_target.get())


class CallerTests(unittest.TestCase):
    def request(self, by_client):
        return SimpleNamespace(state=SimpleNamespace(auth=SimpleNamespace(client_roles=by_client)))

    def roles(self, request, client_id="da-registry-staff-portal"):
        from openg2p_registry_da_extension.register_domain import temporary_platform_overrides as overrides

        token = overrides._current_request.set(request)
        try:
            with mock.patch.dict("os.environ", {"REGISTRY_STAFF_PORTAL_API_KEYCLOAK_CLIENT_ID": client_id}):
                return pr.caller_roles()
        finally:
            overrides._current_request.reset(token)

    def test_outside_a_request_there_is_no_caller(self):
        self.assertIsNone(self.roles(None))

    def test_only_the_roles_of_the_registrys_own_client_count(self):
        request = self.request({"da-registry-staff-portal": ["Intake Officer"],
                                "another-portal": ["Operations Administrator"]})
        self.assertEqual(self.roles(request), {"Intake Officer"})

    def test_without_the_registrys_client_id_nobody_has_a_role(self):
        request = self.request({"da-registry-staff-portal": ["Operations Administrator"]})
        with mock.patch.object(pr, "registry_client_id", return_value=""):
            self.assertEqual(self.roles(request), set())

    def test_a_request_without_a_readable_user_has_no_roles(self):
        self.assertEqual(self.roles(SimpleNamespace(state=SimpleNamespace())), set())


class MetadataTests(unittest.TestCase):
    """The rules are switched off in the metadata for now (18 Nov 2026); the
    code above stays tested and comes back on with the keys."""
    SQL = (SRC / "meta_data" / "zz-oan" / "85_position_and_reporting.sql").read_text()
    STATEMENT = SQL.split("-- See docs/rbac-registry-roles.md section 6.", 1)[1]

    def test_the_rules_are_off_and_the_position_is_a_plain_dropdown(self):
        self.assertNotIn("'oan-value-rights',", self.STATEMENT)
        self.assertNotIn("'oan-change-roles',", self.STATEMENT)
        self.assertIn("'widget', 'select', 'widget-id', 'position'", self.STATEMENT)
        self.assertEqual(pr.field_rules([("Position and reporting", {"panels": []}, False)]), {})

    def test_the_file_says_how_to_switch_them_back_on(self):
        self.assertIn("'oan-value-rights', jsonb_build_object(", self.SQL)
        self.assertIn('"widget": "oan-select-by-right"', self.SQL)


if __name__ == "__main__":
    unittest.main()
