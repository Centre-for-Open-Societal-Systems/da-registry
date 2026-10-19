-- Master Data schema top-up, run by upgrade.sh inside the master-data-api pod
-- before the chart upgrade.
--
-- Generated from the SQLAlchemy models of openg2p_gen2_master_data 1.1.0
-- (image master-data-api:1.1.0-rc.55, the version chart 2.3.0-rc.217 pins):
-- one ADD COLUMN IF NOT EXISTS per model column, nullable columns only, so it
-- is idempotent and keeps every existing row and id. Tables that do not exist
-- are created by the API itself at startup (create_all), which is also why
-- the API cannot add these columns: create_all never alters existing tables.
--
-- Why it is needed: the release ran a pre-rename master-data build whose
-- g2p_geo_levels had three columns. The 1.1.0 geo seed (post-upgrade hook)
-- only upserts rows and writes display_name & co., so without this it fails
-- on its first INSERT. NOT NULL columns are listed as comments: they exist in
-- every build and cannot be added to a populated table anyway.
--
-- Regenerate on a master-data bump:
--   docker run --rm --entrypoint python <master-data-api image> - < (script in README)
BEGIN;
ALTER TABLE IF EXISTS public.g2p_attribute_values ADD COLUMN IF NOT EXISTS "value_id" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_attribute_values ADD COLUMN IF NOT EXISTS "attribute_id" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_attribute_values ADD COLUMN IF NOT EXISTS "value_code" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_attribute_values ADD COLUMN IF NOT EXISTS "value_display" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_attribute_values ADD COLUMN IF NOT EXISTS "parent_value_id" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_attribute_values ADD COLUMN IF NOT EXISTS "sort_order" INTEGER;
ALTER TABLE IF EXISTS public.g2p_attribute_values ADD COLUMN IF NOT EXISTS "display_name_i18n" JSONB;
ALTER TABLE IF EXISTS public.g2p_attribute_values ADD COLUMN IF NOT EXISTS "roles" JSONB;
ALTER TABLE IF EXISTS public.g2p_attribute_values ADD COLUMN IF NOT EXISTS "domain" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_attribute_values ADD COLUMN IF NOT EXISTS "country" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_attribute_values ADD COLUMN IF NOT EXISTS "version" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_attribute_values ADD COLUMN IF NOT EXISTS "valid_from" DATE;
ALTER TABLE IF EXISTS public.g2p_attribute_values ADD COLUMN IF NOT EXISTS "valid_to" DATE;
ALTER TABLE IF EXISTS public.g2p_attributes ADD COLUMN IF NOT EXISTS "attribute_id" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_attributes ADD COLUMN IF NOT EXISTS "attribute_code" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_attributes ADD COLUMN IF NOT EXISTS "attribute_display" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_attributes ADD COLUMN IF NOT EXISTS "is_hierarchical" BOOLEAN;
ALTER TABLE IF EXISTS public.g2p_attributes ADD COLUMN IF NOT EXISTS "display_name_i18n" JSONB;
ALTER TABLE IF EXISTS public.g2p_attributes ADD COLUMN IF NOT EXISTS "country" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_attributes ADD COLUMN IF NOT EXISTS "version" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_attributes ADD COLUMN IF NOT EXISTS "valid_from" DATE;
ALTER TABLE IF EXISTS public.g2p_attributes ADD COLUMN IF NOT EXISTS "valid_to" DATE;
ALTER TABLE IF EXISTS public.g2p_geo_level_values ADD COLUMN IF NOT EXISTS "level_value_id" VARCHAR;
-- SKIPPED (NOT NULL, must already exist): g2p_geo_level_values.level_id VARCHAR
-- SKIPPED (NOT NULL, must already exist): g2p_geo_level_values.level_value_mnemonic VARCHAR
ALTER TABLE IF EXISTS public.g2p_geo_level_values ADD COLUMN IF NOT EXISTS "parent_level_value_id" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_geo_level_values ADD COLUMN IF NOT EXISTS "pcode" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_geo_level_values ADD COLUMN IF NOT EXISTS "pcode_source" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_geo_level_values ADD COLUMN IF NOT EXISTS "boundary_uri" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_geo_level_values ADD COLUMN IF NOT EXISTS "boundary_simplified_uri" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_geo_level_values ADD COLUMN IF NOT EXISTS "display_name" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_geo_level_values ADD COLUMN IF NOT EXISTS "display_name_i18n" JSONB;
ALTER TABLE IF EXISTS public.g2p_geo_level_values ADD COLUMN IF NOT EXISTS "version" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_geo_level_values ADD COLUMN IF NOT EXISTS "valid_from" DATE;
ALTER TABLE IF EXISTS public.g2p_geo_level_values ADD COLUMN IF NOT EXISTS "valid_to" DATE;
ALTER TABLE IF EXISTS public.g2p_geo_levels ADD COLUMN IF NOT EXISTS "level_id" VARCHAR;
-- SKIPPED (NOT NULL, must already exist): g2p_geo_levels.level_mnemonic VARCHAR
ALTER TABLE IF EXISTS public.g2p_geo_levels ADD COLUMN IF NOT EXISTS "parent_level_id" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_geo_levels ADD COLUMN IF NOT EXISTS "display_name" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_geo_levels ADD COLUMN IF NOT EXISTS "display_name_i18n" JSONB;
ALTER TABLE IF EXISTS public.g2p_geo_levels ADD COLUMN IF NOT EXISTS "version" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_geo_levels ADD COLUMN IF NOT EXISTS "valid_from" DATE;
ALTER TABLE IF EXISTS public.g2p_geo_levels ADD COLUMN IF NOT EXISTS "valid_to" DATE;
ALTER TABLE IF EXISTS public.g2p_partners ADD COLUMN IF NOT EXISTS "partner_id" VARCHAR;
-- SKIPPED (NOT NULL, must already exist): g2p_partners.partner_mnemonic VARCHAR
-- SKIPPED (NOT NULL, must already exist): g2p_partners.keymanager_reference_id VARCHAR
-- SKIPPED (NOT NULL, must already exist): g2p_partners.is_active BOOLEAN
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "household_id" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "head_individual_id" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "headship_type" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "size_total" INTEGER;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "dwelling_type" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "tenure_status" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "water_source_type" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "sanitation_type" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "lighting_source" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "cooking_fuel_type" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "geo_pcode" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "address_parts" JSONB;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "latitude" FLOAT;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "longitude" FLOAT;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "country" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_households ADD COLUMN IF NOT EXISTS "version" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "individual_id" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "household_id" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "given_name" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "fathers_name" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "full_name" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "gender" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "relationship_to_head" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "marital_status" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "education_level" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "employment_status" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "disability_status" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "birth_year" INTEGER;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "age" INTEGER;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "phone" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "national_id" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "geo_pcode" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "address_parts" JSONB;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "latitude" FLOAT;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "longitude" FLOAT;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "country" VARCHAR;
ALTER TABLE IF EXISTS public.g2p_sample_individuals ADD COLUMN IF NOT EXISTS "version" VARCHAR;
-- SKIPPED (NOT NULL, must already exist): partner_keys.active BOOLEAN
-- SKIPPED (NOT NULL, must already exist): partner_keys.reference_id VARCHAR
-- SKIPPED (NOT NULL, must already exist): partner_keys.public_key VARCHAR
ALTER TABLE IF EXISTS public.partner_keys ADD COLUMN IF NOT EXISTS "kid" VARCHAR;
-- SKIPPED (NOT NULL, must already exist): partner_keys.algorithm VARCHAR
-- SKIPPED (NOT NULL, must already exist): partner_keys.status VARCHAR
ALTER TABLE IF EXISTS public.partner_keys ADD COLUMN IF NOT EXISTS "valid_from" TIMESTAMP WITHOUT TIME ZONE;
ALTER TABLE IF EXISTS public.partner_keys ADD COLUMN IF NOT EXISTS "valid_to" TIMESTAMP WITHOUT TIME ZONE;
-- SKIPPED (NOT NULL, must already exist): partner_keys.created_at TIMESTAMP WITHOUT TIME ZONE
ALTER TABLE IF EXISTS public.partner_keys ADD COLUMN IF NOT EXISTS "updated_at" TIMESTAMP WITHOUT TIME ZONE;
ALTER TABLE IF EXISTS public.partner_keys ADD COLUMN IF NOT EXISTS "id" INTEGER;
COMMIT;
