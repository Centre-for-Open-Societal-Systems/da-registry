"""Home address: optional, one line, up to 100 characters, on the form and in the API."""

import re
import unittest
from pathlib import Path

from openg2p_registry_da_extension.register_domain.schemas import da as schemas
from openg2p_registry_da_extension.register_domain.services import g2p_register_domain_service_da as service

check = service.G2PRegisterDomainServiceDA._validate_home_address
METADATA = (
    Path(service.__file__).resolve().parents[2] / "meta_data" / "zz-oan" / "96_home_address.sql"
).read_text()


class RuleTests(unittest.TestCase):
    def test_a_record_without_the_field_is_left_alone(self):
        record = {"email": "a@example.org"}
        check(record)
        self.assertEqual(record, {"email": "a@example.org"})

    def test_empty_is_allowed_and_stored_as_nothing(self):
        for value in (None, "", "   "):
            record = {"address_line_1": value}
            check(record)
            self.assertIsNone(record["address_line_1"])

    def test_spaces_around_it_are_dropped(self):
        record = {"address_line_1": "  House 12, Kebele 03, Bahir Dar "}
        check(record)
        self.assertEqual(record["address_line_1"], "House 12, Kebele 03, Bahir Dar")

    def test_a_line_break_is_refused(self):
        # A change request stores what was sent, so tidying it here would not reach the register.
        with self.assertRaises(Exception) as raised:
            check({"address_line_1": "House 12,\nKebele 03"})
        self.assertIn("on one line", str(getattr(raised.exception, "detail", raised.exception)))

    def test_exactly_the_limit_is_accepted(self):
        record = {"address_line_1": "a" * service.HOME_ADDRESS_MAX}
        check(record)
        self.assertEqual(len(record["address_line_1"]), 100)

    def test_one_more_is_refused_with_a_message_that_says_what_to_do(self):
        with self.assertRaises(Exception) as raised:
            check({"address_line_1": "a" * 101})
        self.assertIn("Home address: use 100 characters or fewer", str(getattr(raised.exception, "detail", raised.exception)))


class SchemaAndFormTests(unittest.TestCase):
    def test_the_register_and_intake_schemas_accept_the_field(self):
        for schema in (schemas.G2PRegisterSchemaDA, schemas.G2PIntakeFormSchemaDA):
            self.assertIn("address_line_1", schema.model_fields)

    def test_the_form_states_the_same_limit_and_keeps_the_field_optional(self):
        self.assertEqual(int(re.search(r"'maxLength', (\d+)", METADATA).group(1)), service.HOME_ADDRESS_MAX)
        self.assertIn("'widget-required', false", METADATA)
        self.assertIn(".address_line_1'", METADATA)


if __name__ == "__main__":
    unittest.main()
