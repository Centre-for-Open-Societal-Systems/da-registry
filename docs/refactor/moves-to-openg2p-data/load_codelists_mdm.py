#!/usr/bin/env python3
"""Load the openg2p-data pack's code lists into the local Master Data (MDM) database.

Local docker-compose only (docker/local-dev/data-loaders; to move to
openg2p-data, see README.md in this folder). The DA form's dropdowns read their values from Master
Data (widget-data-source type "api", service "attributes"), and the values come
from the openg2p-data pack: packs/<PACK>/codelists/*.json plus the domains the
registry uses (packs/<PACK>/domains/<domain>/*.json). On a cluster the Master
Data db-seed image (openg2p-data/docker/master-data-db-seed, PACK_LOAD=codelists,
PACK_DOMAINS=agriculture) does this; the compose stack runs the Master Data API
image alone, so this script fills the same two tables from the same files.

Idempotent: every row is upserted on its primary key, so re-running after a pack
change updates displays and sort orders and never duplicates a value. Values the
pack no longer has are left in place (deleting is the catalogue's job, not a
local seed's).

Env: PGHOST/PGPORT/PGDATABASE/PGUSER/PGPASSWORD (the master data DB),
OPENG2P_DATA_DIR (default /openg2p-data), PACK (default ETH-OAN),
PACK_DOMAINS (comma-separated, default agriculture).
"""

import glob
import json
import os
import sys

import psycopg2
from psycopg2.extras import Json


def log(msg: str) -> None:
    print(f"[load-codelists] {msg}", flush=True)


def read_lists(pack_dir: str, domains: list) -> list:
    """[(domain or None, document)] for the core lists and the wanted domains."""
    out = []
    for path in sorted(glob.glob(os.path.join(pack_dir, "codelists", "*.json"))):
        with open(path, encoding="utf-8") as fh:
            out.append((None, json.load(fh)))
    for domain in domains:
        folder = os.path.join(pack_dir, "domains", domain)
        if not os.path.isdir(folder):
            log(f"domain '{domain}' not in pack {pack_dir}: skipped")
            continue
        for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
            with open(path, encoding="utf-8") as fh:
                out.append((domain, json.load(fh)))
    return out


def main() -> int:
    data_dir = os.environ.get("OPENG2P_DATA_DIR", "/openg2p-data")
    pack = os.environ.get("PACK", "ETH-OAN")
    domains = [d.strip() for d in os.environ.get("PACK_DOMAINS", "agriculture").split(",") if d.strip()]
    pack_dir = os.path.join(data_dir, "packs", pack)
    if not os.path.isdir(pack_dir):
        log(f"pack directory not found: {pack_dir}")
        return 1
    with open(os.path.join(pack_dir, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    country = manifest.get("country")
    version = str(manifest.get("version") or "")
    lists = read_lists(pack_dir, domains)
    if not lists:
        log("no code lists found: nothing to do")
        return 0

    conn = psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "master_data"),
        user=os.environ.get("PGUSER", "postgres"),
        password=os.environ.get("PGPASSWORD", ""),
    )
    attrs = values = 0
    try:
        with conn, conn.cursor() as cur:
            for domain, doc in lists:
                cur.execute(
                    """INSERT INTO g2p_attributes
                           (attribute_id, attribute_code, attribute_display, is_hierarchical,
                            display_name_i18n, country, version)
                       VALUES (%s, %s, %s, %s, %s, %s, %s)
                       ON CONFLICT (attribute_id) DO UPDATE SET
                           attribute_code = EXCLUDED.attribute_code,
                           attribute_display = EXCLUDED.attribute_display,
                           is_hierarchical = EXCLUDED.is_hierarchical,
                           display_name_i18n = EXCLUDED.display_name_i18n,
                           country = EXCLUDED.country,
                           version = EXCLUDED.version""",
                    (doc["attribute_id"], doc.get("attribute_code") or doc["attribute_id"],
                     doc.get("attribute_display") or doc["attribute_id"], bool(doc.get("is_hierarchical")),
                     Json(doc.get("display_i18n") or {}), country, version),
                )
                attrs += 1
                for v in doc.get("values") or []:
                    cur.execute(
                        """INSERT INTO g2p_attribute_values
                               (value_id, attribute_id, value_code, value_display, parent_value_id,
                                sort_order, display_name_i18n, roles, domain, country, version)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                           ON CONFLICT (value_id, attribute_id) DO UPDATE SET
                               value_code = EXCLUDED.value_code,
                               value_display = EXCLUDED.value_display,
                               parent_value_id = EXCLUDED.parent_value_id,
                               sort_order = EXCLUDED.sort_order,
                               display_name_i18n = EXCLUDED.display_name_i18n,
                               roles = EXCLUDED.roles,
                               domain = EXCLUDED.domain,
                               country = EXCLUDED.country,
                               version = EXCLUDED.version""",
                        (v["value_id"], doc["attribute_id"], v.get("value_code") or v["value_id"],
                         v.get("value_display") or v["value_id"], v.get("parent_value_id") or v.get("parent_value_code"),
                         v.get("sort_order"), Json(v.get("display_i18n") or {}), Json(v.get("roles") or []),
                         domain, country, version),
                    )
                    values += 1
    finally:
        conn.close()
    log(f"pack {pack} ({version}): {attrs} lists, {values} values upserted "
        f"(domains: {', '.join(domains) or 'core only'}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
