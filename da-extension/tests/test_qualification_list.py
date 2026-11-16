"""Education & professional records and dependents: lists (child registers of DA).

Covers what the registry adds around the platform's list sections: the
required-field checks reading a list section's table and columns, the passout
year and certificate rules of a record, the import template giving a file row
its first record, and the statements that keep the DA record's one-value
fields and the records in step.
"""

import asyncio
import json
import pathlib
import unittest
from unittest import mock
from datetime import date

import jinja2

from openg2p_registry_da_extension import qualification_sync
from openg2p_registry_da_extension.register_domain.services import (
    g2p_register_domain_service_qualification as q,
)
from openg2p_registry_da_extension.register_domain.services import required_fields as rf
from openg2p_registry_da_extension.register_domain.services.ethiopian_calendar import gregorian_to_ethiopic

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "openg2p_registry_da_extension"


def table(required, columns):
    return {"panels": [{"widgets": [{
        "widget": "dialog-table", "widget-label": "Education & Professional",
        "widget-data-path": "reg.records", "widget-required": required,
        "widget-data-columns": [
            {"column-key": key, "widget-label": label, "widget-data-path": key, "widget-required": needed}
            for key, label, needed in columns
        ],
    }]}]}


EDUCATION = table(True, [("education_level", "Education Level", True), ("passout_year", "Passout Year", True),
                         ("joined_date", "Joining Date", False)])
DEPENDENTS = table(False, [("member_name", "Family Member Name", True), ("relationship", "Relationship", True)])


class ListSectionRequirementTests(unittest.TestCase):
    def test_a_required_table_needs_a_row_and_an_optional_one_does_not(self):
        self.assertTrue(rf.list_requires_row(EDUCATION))
        self.assertFalse(rf.list_requires_row(DEPENDENTS))

    def test_a_new_row_must_fill_its_required_columns(self):
        self.assertEqual(rf.row_problems(EDUCATION, {"education_level": "DEGREE"}, absent_is_missing=True),
                         ["fill in Passout Year"])
        self.assertEqual(rf.row_problems(EDUCATION, {"education_level": "DEGREE", "passout_year": 2010},
                                         absent_is_missing=True), [])

    def test_an_update_is_refused_only_for_a_column_it_blanks(self):
        self.assertEqual(rf.row_problems(EDUCATION, {"joined_date": "2015-01-10"}, absent_is_missing=False), [])
        self.assertEqual(rf.row_problems(EDUCATION, {"passout_year": ""}, absent_is_missing=False),
                         ["fill in Passout Year"])

    def test_a_file_row_is_not_asked_for_the_columns_of_a_list(self):
        one_value = {"panels": [{"widgets": [
            {"widget": "select", "widget-label": "Education Level", "widget-data-path": "reg.education_level",
             "widget-required": True}]}]}
        sections = [("Education & Professional", one_value, False), ("Education & Professional", EDUCATION, True),
                    ("Family members / dependents", DEPENDENTS, True)]
        self.assertIsNone(rf.incomplete_reason({"education_level": "DEGREE"}, sections))
        self.assertEqual(rf.incomplete_reason({}, sections),
                         "Required: Education & Professional: fill in Education Level")


class RecordRuleTests(unittest.TestCase):
    def test_passout_year_is_an_ethiopian_year_not_in_the_future(self):
        this_year = gregorian_to_ethiopic(date.today())[0]
        record = {"passout_year": str(this_year)}
        q.check_passout_year(record)
        self.assertEqual(record["passout_year"], this_year)
        for bad in (this_year + 1, 1900, "twenty"):
            with self.assertRaises(Exception):
                q.check_passout_year({"passout_year": bad})
        q.check_passout_year({"passout_year": None})

    def test_a_new_record_needs_every_required_field(self):
        with self.assertRaises(Exception) as raised:
            q._check({"edit_action": "ADD", "education_level": "DEGREE", "specialisation": "AGRONOMY"})
        self.assertIn("Position", str(getattr(raised.exception, "message", raised.exception)))

    def test_no_certificates_is_stored_as_nothing(self):
        for empty in ([], None, ""):
            record = {"certificates": empty}
            asyncio.run(q._certificates(record, q.file_limits([])))
            self.assertIsNone(record["certificates"])

    def test_limits_come_from_the_file_column_of_the_section_metadata(self):
        schema = {"panels": [{"widgets": [{"widget": "dialog-table", "widget-data-columns": [
            {"column-key": "education_level"},
            {"column-key": "certificates",
             "oan-file-rules": {"accept": ".pdf,.jpg,.jpeg,.png,.webp", "maxSize": 2097152, "maxFiles": 3}}]}]}]}
        limits = q.file_limits([("Education & Professional", schema, True)])
        self.assertEqual(limits, {"extensions": {"pdf", "jpg", "jpeg", "png", "webp"}, "max_bytes": 2097152,
                                  "max_files": 3})
        # No metadata: the defaults, which say the same.
        self.assertEqual(q.file_limits([]), limits)

    def test_a_file_of_another_type_or_too_large_is_refused(self):
        limits = q.file_limits([])
        q.check_file("degree.PDF", 2 * 1024 * 1024, limits)
        q.check_file("scan.webp", 10, limits)
        for name, size, part in (("notes.docx", 10, "cannot be attached"), ("noextension", 10, "cannot be attached"),
                                 ("big.pdf", 2 * 1024 * 1024 + 1, "larger than 2 MB")):
            with self.assertRaises(Exception) as raised:
                q.check_file(name, size, limits)
            self.assertIn(part, str(getattr(raised.exception, "message", raised.exception)))

    def test_an_inline_file_is_checked_before_it_is_stored(self):
        too_big = {"__type": "File", "name": "big.pdf", "data": "A" * (4 * (2 * 1024 * 1024 // 3) + 400)}
        wrong = {"__type": "File", "name": "notes.txt", "data": "aGVsbG8="}
        for item in (too_big, wrong):
            with mock.patch.object(q, "_store_file") as store:
                with self.assertRaises(Exception):
                    asyncio.run(q._certificates({"certificates": [item]}, q.file_limits([])))
                store.assert_not_called()

    def test_a_file_the_row_already_carries_is_kept_and_a_new_reference_is_checked(self):
        saved = [{"document_id": "1", "name": "1.pdf"}, {"document_id": "2", "name": "2.pdf"}]
        checked = []

        async def attached(_record):
            return {"1"}

        async def check(document_id, _limits):
            checked.append(document_id)

        with mock.patch.object(q, "_attached_ids", attached), mock.patch.object(q, "_check_reference", check):
            record = {"internal_record_id": "row", "certificates": list(saved)}
            asyncio.run(q._certificates(record, q.file_limits([])))
            self.assertEqual(record["certificates"], saved)
            self.assertEqual(checked, ["2"])
            with self.assertRaises(Exception):
                more = saved + [{"document_id": "3", "name": "3.pdf"}, {"document_id": "4", "name": "4.pdf"}]
                asyncio.run(q._certificates({"internal_record_id": "row", "certificates": more}, q.file_limits([])))


class ImportTemplateTests(unittest.TestCase):
    def render(self, expanded):
        source = (SRC / "templates" / "import_file_to_openg2p_da.json.j2").read_text()
        return json.loads(jinja2.Environment().from_string(source).render(expanded=expanded))

    def test_a_row_becomes_the_first_education_record(self):
        out = self.render({"first_name": "Selam", "education_level": "DEGREE", "specialisation": "AGRONOMY",
                           "position": "DEVELOPMENT_AGENT", "passout_year": 2010, "joined_date": "2015-01-10",
                           "upstream_reference": "REF-1", "source": "CSV_IMPORT"})
        self.assertNotIn("da_service", out)
        (row,) = out["da_qualification"]
        self.assertEqual((row["education_level"], row["passout_year"], row["joined_date"]),
                         ("DEGREE", 2010, "2015-01-10"))
        self.assertRegex(row["internal_record_id"], r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-a[0-9a-f]{3}-[0-9a-f]{12}$")
        self.assertEqual(out["da_identity"][0]["upstream_reference"], "REF-1")

    def test_every_row_gets_its_own_record_id(self):
        ids = {self.render({})["da_qualification"][0]["internal_record_id"] for _ in range(20)}
        self.assertEqual(len(ids), 20)


class SyncStatementTests(unittest.TestCase):
    def test_each_trigger_stands_down_when_the_other_fired_it(self):
        functions = [s for s in qualification_sync.FUNCTIONS if "RETURNS trigger" in s]
        self.assertEqual(len(functions), 2)
        for function in functions:
            self.assertIn("pg_trigger_depth() > 1", function)

    def test_the_main_row_is_the_latest_active_one(self):
        chooser = qualification_sync.FUNCTIONS[0]
        self.assertIn("record_status = 'ACTIVE'", chooser)
        self.assertIn("passout_year DESC NULLS LAST, q.joined_date DESC NULLS LAST", chooser)

    def test_every_mirrored_field_is_written_both_ways(self):
        to_da, _row_changed, to_row = qualification_sync.FUNCTIONS
        for field in qualification_sync.FIELDS:
            self.assertIn(f"{field} = main.{field}", to_da)
            self.assertIn(f"{field} = NEW.{field}", to_row)

    def test_triggers_are_created_not_replaced_and_backfills_are_guarded(self):
        self.assertEqual([(t, n) for t, n, _s in qualification_sync.TRIGGERS],
                         [("g2p_register_qualifications", "da_qualification_row_changed"),
                          ("g2p_register_das", "da_one_value_fields_changed")])
        for _table, _name, statement in qualification_sync.TRIGGERS:
            self.assertNotIn("DROP TRIGGER", statement)
        for _what, needed, _statement in qualification_sync.BACKFILLS:
            self.assertTrue(needed.strip().startswith("SELECT EXISTS"))


if __name__ == "__main__":
    unittest.main()
