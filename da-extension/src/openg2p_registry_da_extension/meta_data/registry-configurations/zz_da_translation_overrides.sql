-- Labels for the DA register. Runs after registry_languages.sql (zz_ prefix),
-- which still carries the farmer registry's wording (e.g. "Farmer ID").

UPDATE "public"."registry_languages"
SET "domain_translation" = (
    COALESCE("domain_translation"::jsonb, '{}'::jsonb)
    || jsonb_build_object(
        'da', 'Development Agents',
        'da_details', 'DA Details',
        'functional_record_id', 'DA-ID',
        'foundational_id', 'Fayda ID',
        'prefix', 'Salutation',
        'first_name', 'Name',
        'middle_name', 'Father Name',
        'last_name', 'Grandfather Name',
        'gender', 'Gender',
        'marital_status', 'Marital Status',
        'birth_month_ec', 'Month of Birth (EC)',
        'birth_year_ec', 'Year of Birth (EC)',
        'mobile_number', 'Phone Number',
        'telegram_number', 'Telegram Number',
        'alternate_number', 'Alternate Number',
        'email', 'Email',
        'education_level', 'Education Level',
        'specialisation', 'Specialisation',
        'position', 'Position',
        'joined_date', 'Joining Date',
        'source', 'Source',
        'region_name', 'Region',
        'zone_name', 'Zone',
        'woreda_name', 'Woreda',
        'kebele_name', 'Kebele'
    )
)::json
WHERE "language_code" = 'en';

UPDATE "public"."registry_languages"
SET "core_translation" = (
    COALESCE("core_translation"::jsonb, '{}'::jsonb)
    || jsonb_build_object(
        'id', 'DA-ID',
        'form_submissions', 'Intake Form',
        'register_form_submissions', '{subject} - Intake Form',
        'register_form_submission', '{subject} - Intake Form',
        'search_form_submissions', 'Search in Intake Form',
        'intake_forms', 'New Intake'
    )
)::json
WHERE "language_code" = 'en';
