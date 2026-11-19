"""Idempotent injection of the sanity DA into the registry database.

Why SQL and not an API:
  * every staff-portal-api register write is a **change request**: using it to
    build a fixture would mean creating and approving a CR before the DCI test
    could run, entangling two tests;
  * the record must exist in a known, ACTIVE, already-approved state so the DCI
    search is deterministic.

Why the test data is injected at all rather than reusing seeded sample data:
the sample DAs are only present when `dbSeed.loadSampleData=true`, which a
production install turns off; the e2e must not depend on them.

**`search_text` is written explicitly.** On the ORM it is auto-populated by
SQLAlchemy event listeners, which do NOT fire for raw SQL. The DCI search is
`search_text ILIKE '%<text>%'`, so this column is what makes the injected
record findable.

`source` is left to its column default (WEB_INTAKE).
"""

from . import fixtures

_COLUMNS = [
    "internal_record_id", "functional_record_id",
    "record_name", "created_by", "created_at",
    "last_approved_at", "last_approved_by",
    "search_text", "record_status",
    "foundational_id", "first_name", "middle_name", "last_name", "given_name",
    "gender", "birth_month_ec", "birth_year_ec", "position", "registration_date",
]

# Re-runnable: a second install/upgrade updates the row rather than colliding on
# the primary key, and resets the change-request field (middle_name) and
# search_text so every run starts from a known state.
_UPSERT = f"""
INSERT INTO "public"."g2p_register_das" ({", ".join(f'"{c}"' for c in _COLUMNS)})
VALUES ({", ".join(["%s"] * len(_COLUMNS))})
ON CONFLICT ("internal_record_id") DO UPDATE SET
    "search_text"    = EXCLUDED."search_text",
    "record_status"  = EXCLUDED."record_status",
    "record_name"    = EXCLUDED."record_name",
    "middle_name"    = EXCLUDED."middle_name",
    "first_name"     = EXCLUDED."first_name",
    "last_name"      = EXCLUDED."last_name",
    "given_name"     = EXCLUDED."given_name",
    "gender"         = EXCLUDED."gender",
    "birth_month_ec" = EXCLUDED."birth_month_ec",
    "birth_year_ec"  = EXCLUDED."birth_year_ec",
    "position"       = EXCLUDED."position";
"""

_CREATED_AT = "2026-01-01 00:00:00"


def _row():
    d = fixtures.FARMER
    full_name = f"{d['first_name']} {fixtures.CR_VALUE_INITIAL} {d['last_name']}"
    # The marker must be inside search_text: that is the only column the DCI
    # search matches on.
    search_text = " ".join([
        fixtures.SEARCH_MARKER,
        fixtures.FARMER_FUNCTIONAL_ID,
        full_name,
        d["gender"],
        d["position"],
    ])
    return (
        fixtures.FARMER_INTERNAL_ID, fixtures.FARMER_FUNCTIONAL_ID,
        full_name, fixtures.CREATED_BY, _CREATED_AT,
        _CREATED_AT, fixtures.CREATED_BY,
        search_text, "ACTIVE",
        fixtures.FARMER_FOUNDATIONAL_ID, d["first_name"], fixtures.CR_VALUE_INITIAL,
        d["last_name"], full_name,
        d["gender"], d["birth_month_ec"], d["birth_year_ec"], d["position"], _CREATED_AT,
    )


def ensure_seeded(cfg) -> str:
    """Insert (or reset) the sanity DA. Returns "seeded"."""
    from . import db

    db.execute(cfg.registry_dsn, _UPSERT, _row())
    return "seeded"


def main() -> int:
    """CLI entrypoint (`python -m sanity.data_seed`) for the deploy-time Job.
    Idempotent; exits 0 on success or benign skip, non-zero on unexpected error."""
    from .config import Config

    cfg = Config.from_env()
    if not cfg.registry_dsn:
        print("[data-seed] registry DB not configured; nothing to seed, skipping")
        return 0
    try:
        status = ensure_seeded(cfg)
    except Exception as exc:  # noqa: BLE001
        print(f"[data-seed] FAILED to seed DA '{fixtures.FARMER_FUNCTIONAL_ID}': {exc}")
        return 1
    print(f"[data-seed] DA '{fixtures.FARMER_FUNCTIONAL_ID}': {status}")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
