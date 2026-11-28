-- DA Registry reporting layer
-- =============================================================================
-- Flattens the register into small, indexed materialized views for reports.
-- A report reads these views, never the g2p_register_* tables, so a change to
-- the register's schema is absorbed here, in the repository that owns it.
--
--   da_rpt_da                one row per DA (g2p_register_das): DA-ID, gender,
--                            position, specialisation, joining date, the DA-ID
--                            they report to, and the work location as codes
--                            and names.
--   da_rpt_da_qualification  one row per education record
--                            (g2p_register_qualifications): level and passout
--                            year, with the DA's position and location carried
--                            down.
--
-- Geography
-- ---------
-- A DA stores each level's Master Data code (OCHA P-code, e.g. ET040301) in
-- region_code .. kebele_code and its name in region_name .. kebele_name. A
-- record approved before those columns were filled has only
-- geo_code_hierarchy_json; its codes are read from there, as the DCI template
-- does (a level's id is "<level>-<code>").
--
-- Personal data
-- -------------
-- Only the DA-ID and the reports-to DA-ID. Names, Fayda ID, phone numbers,
-- e-mail and dates of birth are not carried.
--
-- Record status
-- -------------
-- Every row is kept, whatever its record_status: a report counts ACTIVE
-- records by default and needs the others for a status breakdown.
--
-- Refresh
-- -------
-- Materialized, so Postgres never updates them on its own. The reporting hook
-- re-applies this file on every install/upgrade; a CronJob refreshes them in
-- dependency order (da_rpt_da before da_rpt_da_qualification, which reads it).
-- CONCURRENTLY needs the unique indexes created below.
-- =============================================================================

DROP MATERIALIZED VIEW IF EXISTS da_rpt_da_qualification CASCADE;
DROP MATERIALIZED VIEW IF EXISTS da_rpt_da CASCADE;

-- ---------------------------------------------------------------------------
-- Labels
-- ---------------------------------------------------------------------------
-- The older platform kept list values in g2p_attribute_values; the current one
-- serves them from Master Data and does not create that table (a register
-- installed fresh on it has none). Labels come from that table where it
-- exists; elsewhere the label view is empty and every *_name column falls back
-- to the stored code.
DROP VIEW IF EXISTS da_rpt_attribute_labels CASCADE;
DO $$
BEGIN
  IF to_regclass('public.g2p_attribute_values') IS NOT NULL THEN
    EXECUTE 'CREATE VIEW da_rpt_attribute_labels AS SELECT value_id::text AS value_id, value_display::text AS value_display FROM public.g2p_attribute_values';
  ELSE
    EXECUTE 'CREATE VIEW da_rpt_attribute_labels AS SELECT NULL::text AS value_id, NULL::text AS value_display WHERE false';
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- DAs
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW da_rpt_da AS
SELECT
    da.internal_record_id                                   AS da_record_id,
    NULLIF(TRIM(da.functional_record_id), '')               AS da_id,
    da.record_status,
    NULLIF(TRIM(da.gender), '')                             AS gender,
    COALESCE(NULLIF(TRIM(ge.value_display), ''), NULLIF(TRIM(da.gender), ''))         AS gender_name,
    NULLIF(TRIM(da.position), '')                           AS position,
    COALESCE(NULLIF(TRIM(po.value_display), ''), NULLIF(TRIM(da.position), ''))       AS position_name,
    NULLIF(TRIM(da.specialisation), '')                     AS specialisation,
    COALESCE(NULLIF(TRIM(sp.value_display), ''), NULLIF(TRIM(da.specialisation), '')) AS specialisation_name,
    da.joined_date,
    NULLIF(TRIM(da.reports_to), '')                         AS reports_to_da_id,
    NULLIF(TRIM(da.source), '')                             AS source,
    da.created_at::date                                     AS registration_date,
    da.last_approved_at::date                               AS last_approved_date,

    COALESCE(NULLIF(TRIM(da.region_code), ''), geo.region_code) AS region_code,
    COALESCE(NULLIF(TRIM(da.zone_code), ''),   geo.zone_code)   AS zone_code,
    COALESCE(NULLIF(TRIM(da.woreda_code), ''), geo.woreda_code) AS woreda_code,
    COALESCE(NULLIF(TRIM(da.kebele_code), ''), geo.kebele_code) AS kebele_code,
    NULLIF(TRIM(da.region_name), '')                        AS region_name,
    NULLIF(TRIM(da.zone_name), '')                          AS zone_name,
    NULLIF(TRIM(da.woreda_name), '')                        AS woreda_name,
    NULLIF(TRIM(da.kebele_name), '')                        AS kebele_name
FROM g2p_register_das da
LEFT JOIN LATERAL (
    SELECT
        max(code) FILTER (WHERE lvl = 'region') AS region_code,
        max(code) FILTER (WHERE lvl = 'zone')   AS zone_code,
        max(code) FILTER (WHERE lvl = 'woreda') AS woreda_code,
        max(code) FILTER (WHERE lvl = 'kebele') AS kebele_code
    FROM (
        SELECT lower(COALESCE(e->>'level_mnemonic', e->>'level', ''))               AS lvl,
               NULLIF(regexp_replace(COALESCE(e->>'level_value_id', ''), '^[^-]*-', ''), '') AS code
        FROM jsonb_array_elements(
                 CASE WHEN jsonb_typeof(da.geo_code_hierarchy_json -> 'hierarchy') = 'array'
                      THEN da.geo_code_hierarchy_json -> 'hierarchy' ELSE '[]'::jsonb END) AS e
        WHERE jsonb_typeof(e) = 'object'
    ) levels
) geo ON true
LEFT JOIN da_rpt_attribute_labels ge ON ge.value_id = da.gender
LEFT JOIN da_rpt_attribute_labels po ON po.value_id = da.position
LEFT JOIN da_rpt_attribute_labels sp ON sp.value_id = da.specialisation;

CREATE UNIQUE INDEX IF NOT EXISTS da_rpt_da_pk ON da_rpt_da (da_record_id);
CREATE INDEX IF NOT EXISTS da_rpt_da_position_idx ON da_rpt_da (position);
CREATE INDEX IF NOT EXISTS da_rpt_da_reports_to_idx ON da_rpt_da (reports_to_da_id);
CREATE INDEX IF NOT EXISTS da_rpt_da_geo_idx ON da_rpt_da (region_code, zone_code, woreda_code, kebele_code);

-- ---------------------------------------------------------------------------
-- Education records
-- ---------------------------------------------------------------------------
CREATE MATERIALIZED VIEW da_rpt_da_qualification AS
SELECT
    q.internal_record_id                                    AS qualification_id,
    d.da_record_id,
    d.da_id,
    q.record_status,
    d.record_status                                         AS da_record_status,
    NULLIF(TRIM(q.education_level), '')                     AS education_level,
    COALESCE(NULLIF(TRIM(el.value_display), ''), NULLIF(TRIM(q.education_level), '')) AS education_level_name,
    q.passout_year,
    d.position,
    d.position_name,
    d.specialisation,
    d.region_code, d.zone_code, d.woreda_code, d.kebele_code,
    d.region_name, d.zone_name, d.woreda_name, d.kebele_name
FROM g2p_register_qualifications q
JOIN da_rpt_da d ON d.da_record_id = q.link_internal_record_id
LEFT JOIN da_rpt_attribute_labels el ON el.value_id = q.education_level;

CREATE UNIQUE INDEX IF NOT EXISTS da_rpt_da_qualification_pk ON da_rpt_da_qualification (qualification_id);
CREATE INDEX IF NOT EXISTS da_rpt_da_qualification_da_idx ON da_rpt_da_qualification (da_record_id);
CREATE INDEX IF NOT EXISTS da_rpt_da_qualification_level_idx ON da_rpt_da_qualification (education_level);
CREATE INDEX IF NOT EXISTS da_rpt_da_qualification_geo_idx ON da_rpt_da_qualification (region_code, zone_code, woreda_code, kebele_code);
