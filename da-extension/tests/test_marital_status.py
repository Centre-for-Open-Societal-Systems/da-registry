"""Marital status: optional, from the DA's own list without Unknown (18 Nov 2026)."""

import pathlib
import unittest

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "openg2p_registry_da_extension"
SQL = (SRC / "meta_data" / "zz-oan" / "97_marital_status.sql").read_text()


class MetadataTests(unittest.TestCase):
    def test_the_widget_reads_the_da_list_and_is_optional(self):
        self.assertIn("result ->> 'widget-id' = 'marital_status'", SQL)
        self.assertIn("'{widget-required}', 'false'::jsonb", SQL)
        self.assertIn("'{widget-data-source,params,attribute_id}', '\"DA_MARITAL_STATUS\"'::jsonb", SQL)

    def test_it_runs_before_the_date_widgets_step_and_only_on_the_identity_section(self):
        names = sorted(p.name for p in (SRC / "meta_data" / "zz-oan").glob("*.sql"))
        self.assertLess(names.index("97_marital_status.sql"), names.index("98_ethiopian_dates.sql"))
        self.assertIn('WHERE "section_id" = \'da_identity_section_01\'', SQL)


if __name__ == "__main__":
    unittest.main()
