"""After a location change request the names and codes next to the Kebele id
follow the new place (they used to keep describing the old one).

Imports the DA domain service, so it runs in the container."""

import asyncio
from types import SimpleNamespace
from unittest import mock

from openg2p_registry_da_extension.register_domain.services.g2p_register_domain_service_da import (
    G2PRegisterDomainServiceDA,
)


def entry(level, value_id, name):
    return {"level": level, "level_id": f"level-{level}", "level_mnemonic": level,
            "level_value_id": value_id, "level_value_mnemonic": name}


NEW_CHAIN = {"hierarchy": [entry("country", "country-ET", "Ethiopia"), entry("region", "region-ET03", "Amhara"),
                           entry("zone", "zone-ET0304", "South Wello"), entry("woreda", "woreda-ET030403", "Kutaber"),
                           entry("kebele", "kebele-ET030403101001", "Kutaber")],
             "lowest_level_value_id": "kebele-ET030403101001"}
OLD_FLAT = {"region_name": "Tigray", "zone_name": "North Western", "woreda_name": "Tahtay Adiyabo",
            "kebele_name": "Adi Hageray", "region_code": "ET01", "zone_code": "ET0101", "woreda_code": "ET010101"}
NEW_FLAT = {"region_name": "Amhara", "zone_name": "South Wello", "woreda_name": "Kutaber",
            "kebele_name": "Kutaber", "region_code": "ET03", "zone_code": "ET0304", "woreda_code": "ET030403"}


class Session:
    def __init__(self, row):
        self.row, self.updates = row, []

    async def execute(self, statement, params=None):
        sql = str(statement)
        if sql.startswith("SELECT"):
            return SimpleNamespace(mappings=lambda: SimpleNamespace(first=lambda: self.row))
        self.updates.append((sql, params))


def run(row, lookup):
    service = G2PRegisterDomainServiceDA.__new__(G2PRegisterDomainServiceDA)
    session = Session(row)
    geo = SimpleNamespace(get_geo_hierarchy=mock.AsyncMock(**lookup))
    with mock.patch("openg2p_registry_core.services.G2PGeoHierarchyService.get_component", return_value=geo):
        asyncio.run(service.post_approve(SimpleNamespace(internal_record_id="rec-1"), session))
    return session.updates


def row(flat, chain=NEW_CHAIN, kebele="kebele-ET030403101001"):
    return {"geo_lowest_level_value_id": kebele, "geo_code_hierarchy_json": chain, **flat}


def test_names_and_codes_follow_the_new_kebele():
    (sql, params), = run(row(OLD_FLAT), {"return_value": NEW_CHAIN})
    assert sql.startswith('UPDATE "public"."g2p_register_das" SET')
    assert params == {**NEW_FLAT, "id": "rec-1"}


def test_a_change_that_left_the_location_alone_writes_nothing():
    assert run(row(NEW_FLAT), {"return_value": NEW_CHAIN}) == []


def test_without_master_data_the_chain_the_record_carries_is_used():
    import json

    for lookup in ({"side_effect": RuntimeError("master data down")}, {"return_value": {}}):
        (sql, params), = run(row(OLD_FLAT, chain=json.dumps(NEW_CHAIN)), lookup)
        assert params == {**NEW_FLAT, "id": "rec-1"}


def test_a_record_without_a_location_is_left_alone():
    assert run(row(OLD_FLAT, chain=None, kebele=None), {"return_value": NEW_CHAIN}) == []
    assert run(None, {"return_value": NEW_CHAIN}) == []
