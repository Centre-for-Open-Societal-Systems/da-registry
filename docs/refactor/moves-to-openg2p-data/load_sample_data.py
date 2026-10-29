#!/usr/bin/env python3
"""Load the sample Development Agents from openg2p-data into the DA register.

To move to openg2p-data (see README.md in this folder); the db-seed image no
longer carries it. The local compose stack runs it through
docker/local-dev/data-loaders after the db-seed job. All sample data lives in
the openg2p-data pack, nothing is generated here:

  packs/<PACK>/samples/development_agents.json  the DAs: DA-ID, Fayda FAN,
                                                qualification, specialisation,
                                                position, posting (geo_pcode)
  packs/<PACK>/samples/individuals.json         the people they are: names,
                                                gender, marital status, phone
                                                (the same individuals every OAN
                                                registry seeds from)
  packs/<PACK>/migration/id_map.csv             pack id -> the id a Master Data
                                                seeded before the pack still
                                                carries (e.g. kebele-ET0101...)

The posting is resolved against Master Data (MD_PG* env): the pack's P-code
first, then the pre-pack id from id_map.csv, so the same fixture loads on a
Master Data seeded either way. A DA whose kebele is in neither is loaded
without a posting and reported.

Deterministic and idempotent: internal ids derive from the DA-ID, the insert is
ON CONFLICT DO NOTHING, so re-running never duplicates anything.
"""

import csv
import json
import os
import sys
import uuid

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json

SEEDER = "seeder"
CREATED_AT = "2026-10-01 00:00:00"
NAMESPACE = uuid.UUID("6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90")  # DA register id


def log(msg: str) -> None:
    print(f"[load-sample-data] {msg}", flush=True)


def env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        print(f"[load-sample-data] Missing env var: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def read_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_fixture(pack_dir: str) -> tuple:
    das_doc = read_json(os.path.join(pack_dir, "samples", "development_agents.json"))
    das = das_doc.get("development_agents") if isinstance(das_doc, dict) else das_doc
    individuals = {i["individual_id"]: i for i in read_json(os.path.join(pack_dir, "samples", "individuals.json"))}
    id_map = {}
    path = os.path.join(pack_dir, "migration", "id_map.csv")
    if os.path.exists(path):
        with open(path, encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                id_map.setdefault(row["pack_id"], row["source_id"])
    return das or [], individuals, id_map


def load_geo() -> dict:
    """{level_value_id: (level mnemonic, name, parent id)} from Master Data, or {}."""
    host, dbname = os.environ.get("MD_PGHOST"), os.environ.get("MD_PGDATABASE")
    if not host or not dbname:
        log("MD_PG* not set: DAs are loaded without a posting.")
        return {}
    try:
        conn = psycopg2.connect(
            host=host, port=os.environ.get("MD_PGPORT", "5432"), dbname=dbname,
            user=os.environ.get("MD_PGUSER", ""), password=os.environ.get("MD_PGPASSWORD", ""),
        )
    except Exception as exc:  # noqa: BLE001
        log(f"could not reach master data ({exc}): DAs are loaded without a posting.")
        return {}
    try:
        with conn.cursor() as cur:
            cur.execute("select level_id, level_mnemonic from g2p_geo_levels")
            level_name = dict(cur.fetchall())
            cur.execute("select level_value_id, level_id, level_value_mnemonic, parent_level_value_id"
                        " from g2p_geo_level_values")
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        log(f"could not read master-data geo ({exc}): DAs are loaded without a posting.")
        return {}
    finally:
        conn.close()
    return {vid: (str(level_name.get(lid, lid) or "").lower(), name, parent) for vid, lid, name, parent in rows}


def chain_for(geo: dict, leaf: str) -> list:
    """[(level, name, id)] root -> leaf."""
    chain, seen, cur = [], set(), leaf
    while cur and cur in geo and cur not in seen:
        seen.add(cur)
        level, name, parent = geo[cur]
        chain.append((level, name, cur))
        cur = parent
    chain.reverse()
    return chain


def display(name) -> str:
    return str(name or "").replace("_", " ").replace("-", " ").strip().title()


def flat_names(chain: list) -> dict:
    aliases = {"region": "region", "zone": "zone", "district": "zone", "woreda": "woreda",
               "ward": "woreda", "kebele": "kebele", "village": "kebele"}
    names = {"region": None, "zone": None, "woreda": None, "kebele": None}
    for level, name, _ in chain:
        target = aliases.get(level)
        if target:
            names[target] = display(name)
    return names


def flat_codes(chain: list) -> dict:
    """Master Data codes (P-codes) of region, zone and woreda: the id without a
    level prefix, so "woreda-ET040301" and "ET040301" both give ET040301."""
    codes = {"region": None, "zone": None, "woreda": None}
    for level, _, value_id in chain:
        if level in codes and value_id:
            codes[level] = str(value_id).split("-", 1)[-1]
    return codes


def resolve_posting(geo: dict, id_map: dict, pcode: str):
    """The Master Data id for a pack P-code: itself, or its pre-pack id."""
    for candidate in (pcode, id_map.get(pcode)):
        if candidate and candidate in geo:
            return candidate
    return None


def build_rows(das: list, individuals: dict, geo: dict, id_map: dict) -> list:
    rows, unposted = [], []
    for da in das:
        person = individuals.get(da.get("individual_id")) or {}
        first = person.get("given_name") or da.get("first_name")
        middle = person.get("fathers_name") or da.get("middle_name")
        last = da.get("last_name")
        gender = da.get("gender") or person.get("gender")
        marital = da.get("marital_status") or person.get("marital_status")
        phone = person.get("phone") or ""
        mobile = da.get("mobile_number") or ("0" + phone[4:] if phone.startswith("+251") else phone or None)
        da_id = da["da_id"]
        fan = da["fayda_fan"]
        posting = resolve_posting(geo, id_map, da.get("geo_pcode")) if geo else None
        chain = chain_for(geo, posting) if posting else []
        if da.get("geo_pcode") and not posting:
            unposted.append(da_id)
        names, codes = flat_names(chain), flat_codes(chain)
        hierarchy = {"hierarchy": [{"level_mnemonic": lvl, "level_value_mnemonic": nm, "level_value_id": vid}
                                   for lvl, nm, vid in chain]} if chain else None
        record_name = " ".join(x for x in [first, middle, last] if x)
        search_text = " ".join(x for x in [
            da_id, fan, first, middle, last, mobile, da.get("alternate_number"), da.get("email"),
            da.get("education_level"), da.get("specialisation"), da.get("position"),
            names["region"], names["zone"], names["woreda"], names["kebele"],
        ] if x)
        rows.append((
            str(uuid.uuid5(NAMESPACE, f"sample-{da_id}")), da_id, None, None, record_name, None,
            SEEDER, CREATED_AT, CREATED_AT, SEEDER, search_text, "ACTIVE", None,
            fan, da.get("prefix"), first, middle, last, gender, marital,
            None, CREATED_AT[:10],
            posting, Json(hierarchy) if hierarchy else None,
            da.get("birth_month_ec"), da.get("birth_year_ec"), mobile, da.get("telegram_number"),
            da.get("alternate_number"), da.get("email"),
            da.get("education_level"), da.get("specialisation"), da.get("position"), da.get("joined_date"),
            da.get("source") or "CSV_IMPORT",
            names["region"], names["zone"], names["woreda"], names["kebele"],
            codes["region"], codes["zone"], codes["woreda"],
        ))
    if unposted:
        log(f"{len(unposted)} DA(s) whose kebele is not in Master Data, loaded without a posting: {', '.join(unposted)}")
    return rows


COLUMNS = [
    "internal_record_id", "functional_record_id", "link_internal_record_id", "link_foundational_id",
    "record_name", "record_image_document_id",
    "created_by", "created_at", "last_approved_at", "last_approved_by",
    "search_text", "record_status", "record_status_reason",
    "foundational_id", "prefix", "first_name", "middle_name", "last_name", "gender", "marital_status",
    "phone_numbers", "registration_date",
    "geo_lowest_level_value_id", "geo_code_hierarchy_json",
    "birth_month_ec", "birth_year_ec", "mobile_number", "telegram_number", "alternate_number", "email",
    "education_level", "specialisation", "position", "joined_date", "source",
    "region_name", "zone_name", "woreda_name", "kebele_name",
    "region_code", "zone_code", "woreda_code",
]


def main() -> None:
    data_dir = os.environ.get("OPENG2P_DATA_DIR", "/openg2p-data")
    pack = os.environ.get("PACK", "ETH-OAN")
    pack_dir = os.path.join(data_dir, "packs", pack)
    fixture = os.path.join(pack_dir, "samples", "development_agents.json")
    if not os.path.exists(fixture):
        log(f"no sample DAs in this openg2p-data checkout ({fixture}): nothing loaded.")
        return
    das, individuals, id_map = load_fixture(pack_dir)
    geo = load_geo()
    if geo:
        log(f"master-data geo: {len(geo)} units; pack id map: {len(id_map)} entries.")
    rows = build_rows(das, individuals, geo, id_map)
    conn = psycopg2.connect(
        host=env("PGHOST"), port=os.environ.get("PGPORT", "5432"), dbname=env("PGDATABASE"),
        user=env("PGUSER"), password=env("PGPASSWORD"),
    )
    try:
        with conn, conn.cursor() as cur:
            sql = ('INSERT INTO "public"."g2p_register_das" ('
                   + ", ".join(f'"{c}"' for c in COLUMNS)
                   + ') VALUES %s ON CONFLICT DO NOTHING')
            psycopg2.extras.execute_values(cur, sql, rows, page_size=200)
            log(f"-> g2p_register_das: {len(rows)} sample DAs from pack {pack} ({cur.rowcount} new)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
