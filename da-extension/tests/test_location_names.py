"""The Woreda and Kebele on the list are the ones of the record's Kebele.

The record page shows the place Master Data names for the record's Kebele id;
the list shows the names stored next to it. They differed in two ways: the
stored name was title-cased ("Bure (OR)" read "Bure (Or)"), and a Kebele
changed before change requests refreshed the stored names kept the old place.
The repair is PostgreSQL, so it is tested on a disposable database
(DA_TEST_DATABASE_URL); the rest runs anywhere.
"""

import json
import os
import unittest

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from openg2p_registry_da_extension import startup_migration as sm
from openg2p_registry_da_extension.register_domain.services.g2p_register_domain_service_da import (
    G2PRegisterDomainServiceDA,
)

name_of = G2PRegisterDomainServiceDA._geo_display_name


def chain(region, zone, woreda, kebele, kebele_id="kebele-1"):
    levels = (("country", "country-ET", "Ethiopia"), ("region", "region-ET01", region), ("zone", "zone-ET0101", zone),
              ("woreda", "woreda-ET010101", woreda), ("kebele", kebele_id, kebele))
    return json.dumps({
        "hierarchy": [
            {"level": level, "level_mnemonic": level, "level_value_id": value_id, "level_value_mnemonic": name}
            for level, value_id, name in levels
        ],
        "lowest_level_value_id": kebele_id,
    })


class NameTests(unittest.TestCase):
    def test_the_name_is_kept_as_master_data_spells_it(self):
        for name in ("Bure (OR)", "Dubti town", "Goro (SW Shewa)", "Sokora_diriba"):
            self.assertEqual(name_of({"level_value_mnemonic": name}), name)

    def test_a_display_name_wins_over_the_mnemonic(self):
        self.assertEqual(name_of({"level_value_display_name": "Addis Ababa", "level_value_mnemonic": "addis_ababa"}),
                         "Addis Ababa")

    def test_an_entry_without_a_name_gives_none(self):
        self.assertIsNone(name_of({"level_value_mnemonic": "  "}))


class StatementTests(unittest.TestCase):
    def steps(self, word):
        return [step for step in sm.geo_backfills() if f" {word} on " in step[0]]

    def test_names_and_codes_are_repaired_on_every_da_table(self):
        self.assertEqual(len(self.steps("name")), 4 * len(sm.DA_TABLES))
        self.assertEqual(len(self.steps("code")), 3 * len(sm.DA_TABLES))

    def test_a_differing_value_is_rewritten_only_when_the_chain_ends_at_the_records_kebele(self):
        for _what, needed, statement in self.steps("name") + self.steps("code"):
            for sql in (needed, statement):
                self.assertIn("->-1->>'level_value_id' = t.geo_lowest_level_value_id", sql)

    def test_nothing_is_written_where_the_chain_has_no_value(self):
        for _what, needed, statement in self.steps("name") + self.steps("code"):
            self.assertTrue(needed.strip().startswith("SELECT EXISTS"))
            self.assertTrue(statement.rstrip().endswith("IS NOT NULL"))


@unittest.skipUnless(os.environ.get("DA_TEST_DATABASE_URL"), "Requires owned disposable PostgreSQL")
class RepairTests(unittest.IsolatedAsyncioTestCase):
    COLUMNS = (
        "internal_record_id varchar primary key, geo_lowest_level_value_id varchar, geo_code_hierarchy_json jsonb, "
        "region_name varchar, zone_name varchar, woreda_name varchar, kebele_name varchar, "
        "region_code varchar, zone_code varchar, woreda_code varchar"
    )

    async def asyncSetUp(self):
        self.engine = create_async_engine(os.environ["DA_TEST_DATABASE_URL"])
        async with self.engine.begin() as conn:
            for table in sm.DA_TABLES:
                if (await conn.execute(text("SELECT to_regclass(:name)"), {"name": f"public.{table}"})).scalar():
                    self.created = False
                    self.skipTest("The DA tables exist here: not a disposable database")
            for table in sm.DA_TABLES:
                await conn.execute(text(f'CREATE TABLE "public"."{table}" ({self.COLUMNS})'))
            self.created = True

    async def asyncTearDown(self):
        if getattr(self, "created", False):
            async with self.engine.begin() as conn:
                for table in sm.DA_TABLES:
                    await conn.execute(text(f'DROP TABLE IF EXISTS "public"."{table}"'))
        await self.engine.dispose()

    async def add(self, record_id, kebele_id, hierarchy, names, codes):
        async with self.engine.begin() as conn:
            await conn.execute(
                text(
                    'INSERT INTO "public"."g2p_register_das" VALUES '
                    "(:id, :kebele_id, CAST(:chain AS jsonb), :r, :z, :w, :k, :rc, :zc, :wc)"
                ),
                {"id": record_id, "kebele_id": kebele_id, "chain": hierarchy,
                 "r": names[0], "z": names[1], "w": names[2], "k": names[3],
                 "rc": codes[0], "zc": codes[1], "wc": codes[2]},
            )

    async def row(self, record_id):
        async with self.engine.begin() as conn:
            return tuple((await conn.execute(
                text(
                    "SELECT region_name, zone_name, woreda_name, kebele_name, region_code, zone_code, woreda_code "
                    'FROM "public"."g2p_register_das" WHERE internal_record_id = :id'
                ),
                {"id": record_id},
            )).one())

    async def repair(self):
        ran = []
        async with self.engine.begin() as conn:
            for what, needed, statement in sm.geo_backfills():
                if (await conn.execute(text(needed))).scalar():
                    await conn.execute(text(statement))
                    ran.append(what)
        return ran

    async def test_a_record_left_at_its_old_place_gets_the_names_and_codes_of_its_kebele(self):
        # As DA-5167618350 on dev: the Kebele is in Tigray, the list said Kutaber in Amhara.
        await self.add("moved", "kebele-1", chain("Tigray", "North Western", "Shire Endaslasie town", "Lekatit"),
                       ("Amhara", "South Wello", "Kutaber", "Kutaber"), ("ET03", "ET0304", "ET030403"))
        await self.repair()
        self.assertEqual(await self.row("moved"), ("Tigray", "North Western", "Shire Endaslasie town", "Lekatit",
                                                   "ET01", "ET0101", "ET010101"))

    async def test_a_title_cased_name_gets_master_datas_spelling(self):
        await self.add("cased", "kebele-1", chain("Oromia", "Buno Bedele", "Bure (OR)", "Sokora_diriba"),
                       ("Oromia", "Buno Bedele", "Bure (Or)", "Sokora Diriba"), ("ET01", "ET0101", "ET010101"))
        await self.repair()
        self.assertEqual((await self.row("cased"))[:4], ("Oromia", "Buno Bedele", "Bure (OR)", "Sokora_diriba"))

    async def test_empty_names_are_filled(self):
        await self.add("empty", "kebele-1", chain("Tigray", "North Western", "Tahtay Adiyabo", "Adi Hageray"),
                       (None, None, None, None), (None, None, None))
        await self.repair()
        self.assertEqual(await self.row("empty"), ("Tigray", "North Western", "Tahtay Adiyabo", "Adi Hageray",
                                                   "ET01", "ET0101", "ET010101"))

    async def test_a_chain_that_ends_at_another_kebele_changes_nothing(self):
        before = ("Amhara", "South Wello", "Kutaber", "Kutaber", "ET03", "ET0304", "ET030403")
        await self.add("stale-chain", "kebele-9", chain("Tigray", "North Western", "Shire", "Lekatit"),
                       before[:4], before[4:])
        await self.repair()
        self.assertEqual(await self.row("stale-chain"), before)

    async def test_a_correct_record_needs_nothing_and_a_second_run_does_nothing(self):
        await self.add("fine", "kebele-1", chain("Tigray", "North Western", "Tahtay Adiyabo", "Adi Hageray"),
                       ("Tigray", "North Western", "Tahtay Adiyabo", "Adi Hageray"), ("ET01", "ET0101", "ET010101"))
        self.assertEqual(await self.repair(), [])
        await self.add("cased", "kebele-1", chain("Oromia", "Buno Bedele", "Bure (OR)", "Addislem"),
                       ("Oromia", "Buno Bedele", "Bure (Or)", "Addislem"), ("ET01", "ET0101", "ET010101"))
        self.assertEqual(await self.repair(), ["woreda name on g2p_register_das"])
        self.assertEqual(await self.repair(), [])


if __name__ == "__main__":
    unittest.main()
