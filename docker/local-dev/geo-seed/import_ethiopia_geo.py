#!/usr/bin/env python3
"""Import the real Ethiopia region/zone/woreda/kebele hierarchy from Odoo's
openg2p-ati source (regions.xml, zones.xml, woredas.xml, kebele.sql) into the
Master Data Service's g2p_geo_levels / g2p_geo_level_values tables.

The Master Data Service ships with no bulk-import endpoint (confirmed against
its OpenAPI schema), so this writes directly to Postgres — the same approach
the platform's own db-seed images use for their own seed data.

Usage (from repo root, against a running da_master_data_db):
    docker cp docker/local-dev/geo-seed/import_ethiopia_geo.py da-registry-postgres:/tmp/
    docker exec da-registry-postgres python3 /tmp/import_ethiopia_geo.py \
        --regions /path/to/regions.xml --zones /path/to/zones.xml \
        --woredas /path/to/woredas.xml --kebeles /path/to/kebele.sql \
        --out /tmp/ethiopia_geo_seed.sql
    docker exec -i da-registry-postgres psql -U postgres -d da_master_data_db -f /tmp/ethiopia_geo_seed.sql

This script only *generates* the SQL file (no DB driver dependency needed) —
run it anywhere Python 3 is available, then apply the generated file with psql.
"""
import argparse
import re
import xml.etree.ElementTree as ET


def parse_regions(path):
    """id(odoo xml id) -> {code, name}"""
    tree = ET.parse(path)
    out = {}
    for rec in tree.getroot().findall(".//record[@model='g2p.region']"):
        xml_id = rec.get("id")
        code = rec.find("field[@name='code']").text
        name = rec.find("field[@name='name']").text
        out[xml_id] = {"code": code, "name": name}
    return out


def parse_zones(path):
    """id -> {code, name, region_xml_id}"""
    tree = ET.parse(path)
    out = {}
    for rec in tree.getroot().findall(".//record[@model='g2p.zone']"):
        xml_id = rec.get("id")
        code = rec.find("field[@name='code']").text
        name = rec.find("field[@name='name']").text
        region_ref = rec.find("field[@name='region']").get("ref")
        region_xml_id = region_ref.split(".")[-1]
        out[xml_id] = {"code": code, "name": name, "region_xml_id": region_xml_id}
    return out


def parse_woredas(path):
    """id -> {code, name, zone_xml_id}"""
    tree = ET.parse(path)
    out = {}
    for rec in tree.getroot().findall(".//record[@model='g2p.woreda']"):
        xml_id = rec.get("id")
        code = rec.find("field[@name='code']").text
        name = rec.find("field[@name='name']").text
        zone_ref = rec.find("field[@name='zone']").get("ref")
        zone_xml_id = zone_ref.split(".")[-1]
        out[xml_id] = {"code": code, "name": name, "zone_xml_id": zone_xml_id}
    return out


KEBELE_RE = re.compile(
    r"INSERT INTO g2p_kebele \(code, name, woreda\) VALUES \('([^']*)', '((?:[^'\\]|\\.)*)', "
    r"\(SELECT id FROM g2p_woreda WHERE code = '([^']*)'\)\);"
)


def parse_kebeles(path):
    """list of {code, name, woreda_code}"""
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = KEBELE_RE.match(line.strip())
            if not m:
                continue
            code, name, woreda_code = m.groups()
            name = name.replace("''", "'")
            out.append({"code": code, "name": name, "woreda_code": woreda_code})
    return out


def sql_escape(s):
    return s.replace("'", "''")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--regions", required=True)
    ap.add_argument("--zones", required=True)
    ap.add_argument("--woredas", required=True)
    ap.add_argument("--kebeles", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    regions = parse_regions(args.regions)
    zones = parse_zones(args.zones)
    woredas = parse_woredas(args.woredas)
    kebeles = parse_kebeles(args.kebeles)

    woreda_code_to_value_id = {}
    lines = []

    lines.append("-- Real Ethiopia region/zone/woreda/kebele hierarchy, generated from")
    lines.append("-- openg2p-ati's regions.xml/zones.xml/woredas.xml/kebele.sql.")
    lines.append("BEGIN;")
    lines.append("DELETE FROM g2p_geo_level_values;")
    lines.append("DELETE FROM g2p_geo_levels;")
    lines.append(
        "INSERT INTO g2p_geo_levels (level_id, level_mnemonic, parent_level_id) VALUES\n"
        "  ('l0', 'country', NULL),\n"
        "  ('l1', 'region', 'l0'),\n"
        "  ('l2', 'zone', 'l1'),\n"
        "  ('l3', 'woreda', 'l2'),\n"
        "  ('l4', 'kebele', 'l3');"
    )

    values = []
    values.append("('country-et', 'l0', 'Ethiopia', NULL)")

    for xml_id, r in regions.items():
        value_id = f"region-{r['code']}"
        values.append(
            f"('{value_id}', 'l1', '{sql_escape(r['name'])}', 'country-et')"
        )
        regions[xml_id]["value_id"] = value_id

    for xml_id, z in zones.items():
        value_id = f"zone-{z['code']}"
        region_value_id = regions[z["region_xml_id"]]["value_id"]
        values.append(
            f"('{value_id}', 'l2', '{sql_escape(z['name'])}', '{region_value_id}')"
        )
        zones[xml_id]["value_id"] = value_id

    for xml_id, w in woredas.items():
        value_id = f"woreda-{w['code']}"
        zone_value_id = zones[w["zone_xml_id"]]["value_id"]
        values.append(
            f"('{value_id}', 'l3', '{sql_escape(w['name'])}', '{zone_value_id}')"
        )
        woreda_code_to_value_id[w["code"]] = value_id

    skipped = 0
    for k in kebeles:
        parent_value_id = woreda_code_to_value_id.get(k["woreda_code"])
        if not parent_value_id:
            skipped += 1
            continue
        value_id = f"kebele-{k['code']}"
        values.append(
            f"('{value_id}', 'l4', '{sql_escape(k['name'])}', '{parent_value_id}')"
        )

    # Batch INSERT statements (Postgres handles large multi-row inserts fine,
    # but keep batches modest for readability/diffability).
    batch_size = 500
    for i in range(0, len(values), batch_size):
        batch = values[i : i + batch_size]
        lines.append(
            "INSERT INTO g2p_geo_level_values "
            "(level_value_id, level_id, level_value_mnemonic, parent_level_value_id) VALUES\n  "
            + ",\n  ".join(batch)
            + ";"
        )

    lines.append("COMMIT;")

    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    total = 1 + len(regions) + len(zones) + len(woredas) + (len(kebeles) - skipped)
    print(
        f"Wrote {args.out}: 1 country + {len(regions)} regions + {len(zones)} zones "
        f"+ {len(woredas)} woredas + {len(kebeles) - skipped} kebeles = {total} rows "
        f"({skipped} kebeles skipped — no matching woreda code)"
    )


if __name__ == "__main__":
    main()
