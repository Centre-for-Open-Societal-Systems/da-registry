#!/bin/sh
# Refresh the registry's reporting (materialized) views in dependency order and
# record the outcome of every view, so refresh health can be monitored.
#
# Every outcome is written twice:
#   - one JSON line on stdout ("event": "reporting_view_refresh"), for log
#     collectors, and
#   - one row in reporting_refresh_log (unless REFRESH_LOG_ENABLED=false), for
#     dashboards and alerting queries. reporting_refresh_latest shows the most
#     recent outcome per view.
#
# The job exits non-zero if any view failed, as before.
#
# Environment:
#   PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD  connection (libpq)
#   MATCH_PREFIX                  materialized views to refresh, by name prefix
#   REFRESH_LOG_ENABLED           "true" (default) or "false"
#   REFRESH_LOG_RETENTION_DAYS    log rows kept, in days (default 90)
set -eu

: "${MATCH_PREFIX:?MATCH_PREFIX is required}"
LOG_ENABLED="${REFRESH_LOG_ENABLED:-true}"
RETENTION_DAYS="${REFRESH_LOG_RETENTION_DAYS:-90}"
JOB="$(hostname)"
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-${JOB}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# --- psql scripts -----------------------------------------------------------
# Timing, error capture and JSON are done in psql: it has clock_timestamp() and
# LAST_ERROR_MESSAGE, and it escapes error text correctly, none of which a
# BusyBox shell offers.

# Records one outcome. Variables: run_id job view status concurrent_error error
# sqlstate started_at log_enabled.
cat > "$WORK/record.sql" <<'SQL'
\set ON_ERROR_STOP 1
WITH r AS (
    SELECT :'run_id'                         AS run_id,
           NULLIF(:'view', '')               AS view_name,
           :'status'                         AS status,
           NULLIF(:'concurrent_error', '')   AS concurrent_error,
           NULLIF(:'error', '')              AS error,
           NULLIF(:'sqlstate', '')           AS sqlstate,
           :'started_at'::timestamptz        AS started_at,
           clock_timestamp()                 AS finished_at,
           :'job'                            AS job
)
\if :log_enabled
, logged AS (
    INSERT INTO reporting_refresh_log
           (run_id, view_name, status, concurrent_error, error, sqlstate, started_at, finished_at, duration_ms, job)
    SELECT run_id, view_name, status, concurrent_error, error, sqlstate, started_at, finished_at,
           (extract(epoch FROM finished_at - started_at) * 1000)::int, job
    FROM r
    RETURNING *
)
SELECT jsonb_build_object('event', 'reporting_view_refresh') || to_jsonb(logged) - 'id' FROM logged;
\else
SELECT jsonb_build_object('event', 'reporting_view_refresh',
                          'duration_ms', (extract(epoch FROM finished_at - started_at) * 1000)::int)
       || to_jsonb(r)
FROM r;
\endif
SQL

# Refreshes one view (variable: view), then records it.
cat > "$WORK/refresh-view.sql" <<'SQL'
\set ON_ERROR_STOP 0
SELECT clock_timestamp() AS started_at \gset
SELECT '' AS concurrent_error, '' AS error, '' AS sqlstate \gset
-- CONCURRENTLY so dashboards keep reading the old snapshot while this runs. It
-- needs a unique index, which reporting_views.sql creates.
REFRESH MATERIALIZED VIEW CONCURRENTLY :"view";
\if :ERROR
    -- Fall back to a plain REFRESH rather than skipping: a view added later
    -- without a unique index would otherwise never refresh again. Permanent
    -- silent staleness is worse than the brief lock.
    SELECT :'LAST_ERROR_MESSAGE' AS concurrent_error \gset
    REFRESH MATERIALIZED VIEW :"view";
    \if :ERROR
        SELECT 'failed' AS status, :'LAST_ERROR_MESSAGE' AS error, :'LAST_ERROR_SQLSTATE' AS sqlstate \gset
    \else
        SELECT 'refreshed_blocking' AS status \gset
    \endif
\else
    SELECT 'refreshed' AS status \gset
\endif
\ir record.sql
SQL

# Table and view for the log. Idempotent, so any registry version gets them.
cat > "$WORK/setup.sql" <<'SQL'
\set ON_ERROR_STOP 1
CREATE TABLE IF NOT EXISTS reporting_refresh_log (
    id               bigserial PRIMARY KEY,
    run_id           text        NOT NULL,
    view_name        text,                 -- NULL for run-level events
    status           text        NOT NULL, -- refreshed | refreshed_blocking | failed | skipped
    concurrent_error text,                 -- why CONCURRENTLY failed, when it fell back
    error            text,
    sqlstate         text,
    started_at       timestamptz NOT NULL,
    finished_at      timestamptz NOT NULL,
    duration_ms      integer     NOT NULL,
    job              text
);
CREATE INDEX IF NOT EXISTS reporting_refresh_log_started_idx ON reporting_refresh_log (started_at);
CREATE INDEX IF NOT EXISTS reporting_refresh_log_view_idx ON reporting_refresh_log (view_name, started_at);
COMMENT ON TABLE reporting_refresh_log IS
    'One row per reporting-view refresh outcome, written by the reporting-views refresh job.';
CREATE OR REPLACE VIEW reporting_refresh_latest AS
    SELECT DISTINCT ON (view_name) *
    FROM reporting_refresh_log
    WHERE view_name IS NOT NULL
    ORDER BY view_name, started_at DESC;
SQL

# --- helpers ----------------------------------------------------------------

db_now() { psql -qtA -X -c "SELECT clock_timestamp()" 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ; }

# record STATUS VIEW ERROR STARTED_AT: log an event that is not a view refresh.
record() {
    psql -qtA -X \
        -v run_id="$RUN_ID" -v job="$JOB" -v log_enabled="$LOG_ENABLED" \
        -v status="$1" -v view="$2" -v error="$3" -v started_at="$4" \
        -v concurrent_error= -v sqlstate= \
        -f "$WORK/record.sql"
}

# --- run --------------------------------------------------------------------

if [ "$LOG_ENABLED" = "true" ]; then
    if ! psql -qtA -X -f "$WORK/setup.sql" >/dev/null 2>"$WORK/err"; then
        # Logging must never stop the refresh itself.
        printf '{"event": "reporting_refresh_log_unavailable", "run_id": "%s"}\n' "$RUN_ID"
        sed 's/^/[refresh]   /' "$WORK/err" >&2
        LOG_ENABLED=false
    fi
fi

STARTED="$(db_now)"

# Dependency order, from pg_depend: views nobody reads come first (lvl 0); a
# view built on another follows it.
if ! ORDER=$(psql -qtA -X -v prefix="$MATCH_PREFIX" 2>"$WORK/err" <<'SQL'
WITH RECURSIVE mv AS (
    SELECT c.oid, c.relname
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'm' AND n.nspname = 'public'
      AND c.relname LIKE :'prefix' || '%'
), edge AS (
    SELECT DISTINCT r.ev_class AS child, d.refobjid AS parent
    FROM pg_depend d JOIN pg_rewrite r ON r.oid = d.objid
    WHERE d.classid = 'pg_rewrite'::regclass
      AND r.ev_class <> d.refobjid
      AND r.ev_class IN (SELECT oid FROM mv)
      AND d.refobjid IN (SELECT oid FROM mv)
), depth AS (
    SELECT oid, 0 AS lvl FROM mv WHERE oid NOT IN (SELECT child FROM edge)
    UNION ALL
    SELECT e.child, d.lvl + 1 FROM edge e JOIN depth d ON d.oid = e.parent
)
SELECT mv.relname
FROM mv JOIN (SELECT oid, max(lvl) AS lvl FROM depth GROUP BY oid) t
  ON t.oid = mv.oid
ORDER BY t.lvl, mv.relname;
SQL
); then
    record failed "" "view discovery failed: $(cat "$WORK/err")" "$STARTED" || true
    exit 1
fi

if [ -z "$ORDER" ]; then
    # Not a failure, but it must be visible: the views are created by a
    # post-install hook, so an early first run legitimately finds none.
    record skipped "" "no materialized views matching '${MATCH_PREFIX}%'" "$STARTED"
    exit 0
fi

rc=0
for v in $ORDER; do
    # psql's own error output is not needed: the outcome line carries it.
    if out=$(psql -qtA -X \
            -v run_id="$RUN_ID" -v job="$JOB" -v log_enabled="$LOG_ENABLED" -v view="$v" \
            -f "$WORK/refresh-view.sql" 2>"$WORK/err"); then
        echo "$out"
        case "$out" in *'"status": "failed"'*) rc=1 ;; esac
    else
        # Recording the outcome failed; the refresh outcome is unknown.
        record failed "$v" "could not record refresh outcome: $(cat "$WORK/err")" "$(db_now)" || true
        rc=1
    fi
done

if [ "$LOG_ENABLED" = "true" ]; then
    psql -qtA -X -v days="$RETENTION_DAYS" >/dev/null 2>&1 <<'SQL' || true
DELETE FROM reporting_refresh_log WHERE started_at < now() - make_interval(days => :'days'::int);
SQL
fi

exit $rc
