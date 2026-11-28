"""The db-seed image carries the da_rpt_* reporting views, and the chart's hook applies them safely."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = ROOT / "docker" / "db-seed"
CHART = ROOT / "helm" / "openg2p-da-registry"
VIEWS = ("da_rpt_da", "da_rpt_da_qualification")


def read(path):
    return path.read_text(encoding="utf-8")


class DbSeedReportingViewsTests(unittest.TestCase):
    def test_the_image_carries_the_views_after_the_seed_cleanup(self):
        text = read(SEED / "Dockerfile")
        copy = "COPY docker/db-seed/reporting_views.sql /seed/reporting_views.sql"
        self.assertIn(copy, text)
        self.assertGreater(text.index(copy), text.index("rm -rf /seed/meta_data/*"))

    def test_the_views_are_idempotent(self):
        sql = read(SEED / "reporting_views.sql")
        for view in VIEWS:
            self.assertIn(f"DROP MATERIALIZED VIEW IF EXISTS {view} CASCADE;", sql)
            self.assertIn(f"CREATE MATERIALIZED VIEW {view} AS", sql)
            # REFRESH ... CONCURRENTLY needs a unique index on every view.
            self.assertRegex(sql, rf"CREATE UNIQUE INDEX IF NOT EXISTS \w+ ON {view} \(")
        self.assertNotIn("\r", sql)
        for line in sql.splitlines():
            if line.startswith("CREATE") and "INDEX" in line:
                self.assertIn("IF NOT EXISTS", line)

    def test_the_qualification_view_is_dropped_before_the_view_it_reads(self):
        sql = read(SEED / "reporting_views.sql")
        self.assertLess(sql.index("DROP MATERIALIZED VIEW IF EXISTS da_rpt_da_qualification"),
                        sql.index("DROP MATERIALIZED VIEW IF EXISTS da_rpt_da CASCADE"))
        self.assertLess(sql.index("CREATE MATERIALIZED VIEW da_rpt_da AS"),
                        sql.index("CREATE MATERIALIZED VIEW da_rpt_da_qualification AS"))

    def test_no_personal_data_is_carried(self):
        sql = read(SEED / "reporting_views.sql")
        body = sql[sql.index("CREATE MATERIALIZED VIEW da_rpt_da AS"):]
        for column in ("first_name", "middle_name", "last_name", "record_name", "foundational_id",
                       "mobile_number", "telegram_number", "alternate_number", "email",
                       "birth_month_ec", "birth_year_ec", "search_text"):
            self.assertNotRegex(body, rf"\b{column}\b", column)

    def test_the_hook_waits_for_every_table_the_views_read(self):
        sql = read(SEED / "reporting_views.sql")
        hook = read(CHART / "templates" / "reporting-views.yaml")
        for table in sorted(set(re.findall(r"\b(?:FROM|JOIN)\s+(g2p_\w+)", sql))):
            self.assertIn("'" + table + "'", hook, table)

    def test_the_hook_waits_for_the_latest_da_columns(self):
        hook = read(CHART / "templates" / "reporting-views.yaml")
        self.assertIn("table_name = 'g2p_register_das' AND column_name IN ('reports_to', 'region_code', 'kebele_code')", hook)

    def test_the_views_do_not_need_the_legacy_attribute_table(self):
        # A register installed on the current platform has no g2p_attribute_values (Crop sown staging 53).
        sql = read(SEED / "reporting_views.sql")
        hook = read(CHART / "templates" / "reporting-views.yaml")
        self.assertNotIn("JOIN g2p_attribute_values", sql)
        self.assertIn("to_regclass('public.g2p_attribute_values') IS NOT NULL", sql)
        self.assertNotIn("'g2p_attribute_values'", hook)
        self.assertLess(sql.index("CREATE VIEW da_rpt_attribute_labels"), sql.index("CREATE MATERIALIZED VIEW da_rpt_da AS"))

    def test_the_refresh_job_matches_the_views(self):
        refresh = read(CHART / "templates" / "reporting-views-refresh.yaml")
        self.assertIn("value: da_rpt_", refresh)
        self.assertIn('.Files.Get "files/reporting-views-refresh.sh"', refresh)
        self.assertTrue((CHART / "files" / "reporting-views-refresh.sh").is_file())

    def test_the_views_are_off_by_default_and_on_in_the_dev_deploy(self):
        values = read(CHART / "values.yaml").replace("\r\n", "\n")
        self.assertIn("reporting:\n  db:", values)
        self.assertIn("  views:\n    enabled: false\n", values)
        self.assertIn("reporting:\n  views:\n    enabled: true\nEOF2", read(ROOT / "ci" / "deploy-dev.sh"))


if __name__ == "__main__":
    unittest.main()
