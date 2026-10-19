#!/usr/bin/env python3
"""Load synthetic Development Agents into the DA register (local dev only).

Run by the db-seed image when LOAD_SAMPLE_DATA=true. Writes N synthetic DAs
straight into g2p_register_das. Each DA is posted to a real kebele read from
Master Data (MD_PG* env), so the geo hierarchy and the flattened
region/zone/woreda/kebele names match what the portal shows.

Deterministic: the same N rows are produced on every run, and the insert is
ON CONFLICT DO NOTHING, so re-running the seed never duplicates anything.
No real people: names are drawn from common Ethiopian given names and every
Fayda FIN / phone number is synthetic.
"""

import os
import random
import sys
import uuid

import psycopg2
import psycopg2.extras
from psycopg2.extras import Json

SEEDER = "seeder"
CREATED_AT = "2026-10-01 00:00:00"
COUNT = int(os.environ.get("DA_SAMPLE_COUNT", "50"))
NAMESPACE = uuid.UUID("6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90")  # DA register id

MALE = ["Abebe", "Tadesse", "Kebede", "Dawit", "Yohannes", "Mulugeta", "Getachew", "Solomon",
        "Tesfaye", "Bekele", "Alemayehu", "Girma", "Haile", "Mesfin", "Fikru", "Lemma"]
FEMALE = ["Hana", "Meseret", "Selamawit", "Tigist", "Rahel", "Almaz", "Birtukan", "Genet",
          "Hiwot", "Mahlet", "Tsion", "Frehiwot", "Aster", "Senait", "Yeshi", "Zewditu"]
FATHER = ["Alemu", "Girma", "Bekele", "Tesfaye", "Assefa", "Wolde", "Mulugeta", "Negash",
          "Haile", "Desta", "Kassa", "Tadesse", "Abebe", "Lemma", "Gebre", "Worku"]
SALUTATION = ["MR", "MRS", "DR", None]
MARITAL = ["SINGLE", "MARRIED", "MARRIED", "DIVORCED", "WIDOWED"]
EDUCATION_LEVEL = ["CERTIFICATE", "DIPLOMA", "DIPLOMA", "DEGREE", "DEGREE", "MASTERS"]
POSITION = ["DEVELOPMENT_AGENT", "DEVELOPMENT_AGENT", "DEVELOPMENT_AGENT", "SENIOR_DA"]
SPECIALISATION = ["CROP_PRODUCTION", "LIVESTOCK", "NATURAL_RESOURCES", "AGRONOMY", "HORTICULTURE"]
SOURCE = "CSV_IMPORT"


def log(msg: str) -> None:
    print(f"[load-sample-data] {msg}")


def env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        print(f"[load-sample-data] Missing env var: {name}", file=sys.stderr)
        sys.exit(1)
    return value


def load_kebeles() -> list:
    """Return [(lowest_id, [chain root->leaf of (level_mnemonic, name, id)])]
    for units at the lowest geo level in Master Data, or [] if unavailable."""
    host, dbname = os.environ.get("MD_PGHOST"), os.environ.get("MD_PGDATABASE")
    if not host or not dbname:
        log("MD_PG* not set: DAs are loaded without a posting.")
        return []
    try:
        conn = psycopg2.connect(
            host=host, port=os.environ.get("MD_PGPORT", "5432"), dbname=dbname,
            user=os.environ.get("MD_PGUSER", ""), password=os.environ.get("MD_PGPASSWORD", ""),
        )
    except Exception as exc:  # noqa: BLE001
        log(f"could not reach master data ({exc}): DAs are loaded without a posting.")
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("select level_id, level_mnemonic from g2p_geo_levels")
            level_name = dict(cur.fetchall())
            cur.execute("select level_value_id, level_id, level_value_mnemonic, parent_level_value_id"
                        " from g2p_geo_level_values")
            rows = cur.fetchall()
    except Exception as exc:  # noqa: BLE001
        log(f"could not read master-data geo ({exc}): DAs are loaded without a posting.")
        return []
    finally:
        conn.close()

    by_id = {vid: (level_name.get(lid, lid), name, parent) for vid, lid, name, parent in rows}
    # Post DAs to kebeles only. Some woredas have no kebeles in the pack, so
    # "units without children" would also pick those woredas.
    leaves = sorted(vid for vid, (level, _, _) in by_id.items() if str(level or "").lower() == "kebele")
    if not leaves:
        parents = {parent for _, _, _, parent in rows if parent}
        leaves = sorted(vid for vid in by_id if vid not in parents)
    out = []
    for leaf in leaves:
        chain, seen, cur = [], set(), leaf
        while cur and cur in by_id and cur not in seen:
            seen.add(cur)
            level, name, parent = by_id[cur]
            chain.append((str(level or "").lower(), name, cur))
            cur = parent
        chain.reverse()
        out.append((leaf, chain))
    log(f"master-data geo: {len(out)} lowest-level units available.")
    return out


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


def build_rows(kebeles: list) -> list:
    rnd = random.Random(20261001)
    used_fin, rows = set(), []
    for i in range(COUNT):
        female = i % 2 == 1
        first = rnd.choice(FEMALE if female else MALE)
        father = rnd.choice(FATHER)
        grandfather = rnd.choice(FATHER)
        while True:
            fin = str(rnd.randint(200000000000, 999999999999))
            if fin not in used_fin:
                used_fin.add(fin)
                break
        # Ethiopian calendar: 1964-1992 EC is roughly 1972-2000 GC.
        birth_year_ec = rnd.randint(1964, 1992)
        birth_month_ec = rnd.randint(1, 13)
        joined_date = f"{rnd.randint(max(birth_year_ec + 28, 2005), 2026)}-{rnd.randint(1, 9):02d}-{rnd.randint(1, 28):02d}"
        mobile = "09" + str(rnd.randint(10000000, 99999999))
        alternate = "07" + str(rnd.randint(10000000, 99999999)) if i % 3 == 0 else None
        email = f"{first.lower()}.{father.lower()}{i + 1}@example.org"
        salutation = "MRS" if female and i % 4 == 1 else rnd.choice(["MR", "DR", None]) if not female else None
        marital = rnd.choice(MARITAL)
        education = rnd.choice(EDUCATION_LEVEL)
        spec = rnd.choice(SPECIALISATION)
        position = rnd.choice(POSITION)
        da_id = f"DA-{3500000001 + i}"
        internal_id = str(uuid.uuid5(NAMESPACE, f"sample-da-{i}"))

        geo_id, hierarchy, names, codes = None, None, flat_names([]), flat_codes([])
        if kebeles:
            leaf, chain = kebeles[rnd.randrange(len(kebeles))]
            geo_id = leaf
            hierarchy = {"hierarchy": [{"level_mnemonic": lvl, "level_value_mnemonic": nm,
                                        "level_value_id": vid} for lvl, nm, vid in chain]}
            names = flat_names(chain)
            codes = flat_codes(chain)

        record_name = " ".join([first, father, grandfather])
        search_text = " ".join(x for x in [
            da_id, fin, first, father, grandfather, mobile, alternate, email, education, spec, position,
            names["region"], names["zone"], names["woreda"], names["kebele"],
        ] if x)

        rows.append((
            internal_id, da_id, None, None, record_name, None,
            SEEDER, CREATED_AT, CREATED_AT, SEEDER, search_text, "ACTIVE", None,
            fin, salutation, first, father, grandfather, "FEMALE" if female else "MALE", marital,
            # phone_numbers (platform JSON) is left empty; the flat
            # mobile_number column below is what the DA register uses.
            None, CREATED_AT[:10],
            geo_id, Json(hierarchy) if hierarchy else None,
            birth_month_ec, birth_year_ec, mobile, mobile, alternate, email,
            education, spec, position, joined_date, SOURCE,
            names["region"], names["zone"], names["woreda"], names["kebele"],
            codes["region"], codes["zone"], codes["woreda"],
        ))
    return rows


def flat_codes(chain: list) -> dict:
    """Master Data codes (OCHA P-codes) of region, zone and woreda: the part of
    each level's id after its type, e.g. "woreda-ET040301" -> "ET040301"."""
    codes = {"region": None, "zone": None, "woreda": None}
    for level, _, value_id in chain:
        if level in codes and value_id:
            codes[level] = str(value_id).split("-", 1)[-1]
    return codes


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
    rows = build_rows(load_kebeles())
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
            log(f"-> g2p_register_das: {len(rows)} synthetic DAs offered ({cur.rowcount} new)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
