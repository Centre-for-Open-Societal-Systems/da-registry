-- Label casing: sentence case for everything staff read that OAN metadata defines.
-- Labels, section and tab titles, table headings, messages and dropdown filter
-- labels use sentence case; acronyms and proper nouns (ID, FAN, FIN, Fayda,
-- Kebele, Woreda, ODK, DA) keep their case, and raw codes are not shown as
-- labels. Only display text changes: translation keys, ids, codes and
-- mnemonics are untouched.
--
-- Every statement is an explicit-id UPDATE (or a merge of named translation
-- keys), so it is idempotent and a plain upgrade applies it to databases that
-- already hold the older text. It sorts after the older seed files of this
-- package, so it also wins on a fresh install.

-- Display labels: domain translations (English)
UPDATE "public"."registry_languages"
SET "domain_translation" = (COALESCE("domain_translation"::jsonb, '{}'::jsonb) ||
'{
 "access_to_finance": "Access to finance",
 "access_to_machinery": "Access to machinery",
 "add_consent_receipt": "Add consent receipt",
 "add_consent_request": "Add consent request",
 "add_crop": "Add crop",
 "add_farm": "Add farm",
 "add_farm_input": "Add farm input",
 "add_livestock_record": "Add livestock record",
 "add_member": "Add member",
 "add_phone": "Add phone",
 "address_line_1": "Address line 1",
 "address_line_2": "Address line 2",
 "allowed_data_fields": "Allowed data fields",
 "A_LOT_OF_DIFFICULTY": "A lot of difficulty",
 "alternate_number": "Alternate number",
 "amount_fertilizer_utilized": "Amount fertilizer utilized",
 "amount_improved_seed_utilized": "Amount improved seed utilized",
 "amount_insecticide_utilized": "Amount insecticide utilized",
 "amount_pesticide_utilized": "Amount pesticide utilized",
 "area_in_hectare": "Area in hectare",
 "attribute_list": "Attribute list",
 "BIOFUELS_NONFOOD": "Biofuels (non-food)",
 "birth_date": "Date of birth (GC)",
 "birth_date_ec": "Date of birth (EC)",
 "birth_information": "Birth information",
 "birth_month_ec": "Month of birth (EC)",
 "birth_year_ec": "Year of birth (EC)",
 "body_condition": "Body condition",
 "CANNOT_DO_AT_ALL": "Cannot do at all",
 "CAN_READ_AND_WRITE": "Can read and write",
 "certificate_provided": "Certificate provided",
 "certificate_storage_id": "Land certificate",
 "click_to_search_household": "Click to search household",
 "computation_scores": "Computation scores",
 "consent_partner_name": "Consent partner name",
 "consent_receipts": "Consent receipts",
 "consent_requests": "Consent requests",
 "consent_type": "Consent type",
 "cooperative_union": "Cooperative union",
 "cooperative_union_name": "Cooperative union name",
 "country_code": "Country code",
 "CROP_PRODUCTION": "Crop production",
 "CROP_SHARE": "Crop share",
 "current_land_use": "Current land use",
 "da_details": "DA details",
 "da": "Development agents",
 "data_collection_date": "Data collection date",
 "disability_severity": "Disability severity",
 "disability_type": "Disability type",
 "DIVORCE_SETTLEMENT": "Divorce settlement",
 "DONATION_GIFT": "Donation / gift",
 "education_level": "Education level",
 "end_use": "End use",
 "enter_address_line_1": "Enter address line 1",
 "enter_address_line_2": "Enter address line 2",
 "enter_altitude": "Enter altitude",
 "enter_latitude": "Enter latitude",
 "enter_longitude": "Enter longitude",
 "enumerator_accuracy": "Enumerator accuracy",
 "enumerator_altitude": "Enumerator altitude",
 "enumerator_identity": "Enumerator identity",
 "enumerator_latitude": "Enumerator latitude",
 "enumerator_longitude": "Enumerator longitude",
 "enumerator_name": "Enumerator name",
 "enumerator_user_id": "Enumerator user ID",
 "expiry_date": "Expiry date",
 "family_size": "Family size",
 "farmer_birth_information": "Birth information",
 "farmer_cluster": "Farmer cluster",
 "farmer_cluster_role": "Farmer cluster role",
 "farmer_consent_receipts": "Consent receipts",
 "farmer_consent_receipts_intake_tab": "Consent receipts intake",
 "farmer_consent_receipts_tab": "Consent receipts",
 "farmer_consent_requests": "Consent requests",
 "farmer_consent_requests_intake_tab": "Consent requests intake",
 "farmer_consent_requests_tab": "Consent requests",
 "farmer_enumerator": "Enumerator details",
 "farmer_enumerator_intake_tab": "Enumerator intake",
 "farmer_farm_inputs": "Farm inputs",
 "farmer_farm_inputs_tab": "Farm inputs",
 "farmer_household_information": "Household information",
 "farmer_household_location": "Household location",
 "farmer_household_members": "Household members",
 "farmer_ids_intake_tab": "IDs intake",
 "farmer_ingestion_intake": "Farmer ingestion intake",
 "farmer_intake": "Farmer intake",
 "farmer_intake_tab": "Farmer intake",
 "farmer_location_intake_tab": "Location intake",
 "farmer_personal_information": "Personal information",
 "farmer_phone_numbers": "Phone numbers",
 "farmer_socio_economic_and_health": "Socio-economic & health details",
 "farming_type": "Farming type",
 "farm_inputs": "Farm inputs",
 "FarmInputs": "Farm inputs",
 "father_included": "Father included",
 "FEED_ANIMALS": "Feed animals",
 "fertilizer_use": "Fertilizer use",
 "first_name_afaan_oromo": "First name (Afaan Oromo)",
 "first_name_amharic": "First name (Amharic)",
 "first_name_english": "First name (English)",
 "FOOD_HUMAN_CONSUMPTION": "Food (human consumption)",
 "fr_farmer_farm_input": "Farm inputs",
 "fr_farmer_personal_info": "Personal information",
 "fr_farmer_socio_and_health": "Socio and health",
 "fr_household_information": "Household information",
 "GOVERNMENT_NGO_SUPPORT": "Government / NGO support",
 "head_count": "Head count",
 "health_details": "Health details",
 "hh_farmer_personal_info": "Personal information",
 "hh_farmer_socio_and_health": "Socio and health",
 "hh_household_information": "Household information",
 "HIGHER_EDUCATION": "Higher education",
 "household_computation_scores": "Computation scores",
 "household_farmer_location_details": "Location details",
 "household_farmer_personal_information": "Personal information",
 "household_head": "Household head",
 "household_household_information": "Household information",
 "household_income": "Household income",
 "household_information": "Household information",
 "household_ingestion_intake": "Household ingestion intake",
 "household_intake_tab": "Household intake",
 "HouseholdMember": "Household members",
 "household_members": "Household members",
 "household_members_records": "Household members records",
 "household_socio_economic_and_health": "Socio-economic & health details",
 "id_type": "ID type",
 "import_source": "Import source",
 "improved_seed_use": "Improved seed use",
 "insecticide_use": "Insecticide use",
 "is_cooperative_union_member": "Is cooperative union member",
 "is_farmer_cluster_member": "Is farmer cluster member",
 "is_household_head": "Are you a household head?",
 "is_primary_cooperative_member": "Is primary cooperative member",
 "is_primary_phone": "Primary phone",
 "is_psnp_user": "PSNP user",
 "joined_date": "Joining date",
 "land_kebele": "Land Kebele is in",
 "land_ownership": "Land ownership",
 "land_ownership_type": "Land ownership type",
 "land_size": "Land size",
 "land_summary": "Land summary",
 "language_spoken": "Primary language",
 "last_name_afaan_oromo": "Last name (Afaan Oromo)",
 "last_name_amharic": "Last name (Amharic)",
 "last_name_english": "Last name (English)",
 "last_name": "Grandfather name",
 "LIVESTOCK_PRODUCTION": "Livestock production",
 "livestock_system": "Livestock system",
 "livestock_type": "Livestock type",
 "local_language": "Local language",
 "location_details": "Location details",
 "marital_status": "Marital status",
 "means_of_acquisition": "Means of acquisition",
 "MembershipDetails": "Membership details",
 "middle_name_afaan_oromo": "Middle name (Afaan Oromo)",
 "middle_name_amharic": "Middle name (Amharic)",
 "middle_name_english": "Middle name (English)",
 "middle_name": "Father name",
 "mobile_number": "Phone number",
 "mother_included": "Mother included",
 "NO_DIFFICULTY": "No difficulty",
 "NOMADIC_PASTORAL": "Nomadic pastoral",
 "number_of_children_in_family": "Number of children in the family",
 "number_of_children": "Number of children",
 "number_of_female_members": "Number of female members",
 "number_of_females_in_family": "Number of females in the family",
 "number_of_male_members": "Number of male members",
 "number_of_males_in_family": "Number of males in the family",
 "num_female_members": "Number of female members",
 "num_male_members": "Number of male members",
 "originated_from": "Originated from",
 "other_land_owner": "Other land owner",
 "personal_information": "Personal information",
 "pesticide_use": "Pesticide use",
 "phone_number": "Phone number",
 "phone_type": "Phone type",
 "planted_date": "Planted date",
 "postal_code": "Postal code",
 "primary_commodity": "Primary commodity",
 "primary_cooperative_name": "Primary cooperative name",
 "primary_cooperative": "Primary cooperative",
 "primary_language": "Primary language",
 "production_type": "Production type",
 "record_name": "Record name",
 "record_workflow": "Record workflow",
 "register_fr_farmer_crops": "Farmer crops",
 "rejection_reason": "Rejection reason",
 "related_consent_request_id": "Related consent request",
 "RENTING_LEASING": "Renting / leasing",
 "search_by_name_or_id": "Search by name or ID",
 "SEDENTARY_PASTORAL": "Sedentary pastoral",
 "select_household": "Select household",
 "SELF_CARE": "Self care",
 "SEMI_NOMADIC": "Semi nomadic",
 "signature_algorithm": "Signature algorithm",
 "signed_at": "Signed at",
 "size_of_group": "Size of group",
 "socio_economic_and_health": "Socio-economic & health details",
 "socio_economic_details": "Socio economic details",
 "socio_economic": "Socio-economic details",
 "soil_fertility": "Soil fertility",
 "SOME_DIFFICULTY": "Some difficulty",
 "source_of_income": "Source of income",
 "SQUARE_FOOT": "Square foot",
 "SQUARE_KM": "Square km",
 "SQUARE_METER": "Square meter",
 "SQUARE_YARD": "Square yard",
 "sub_region": "Sub region",
 "telegram_number": "Telegram number",
 "total_crop_sharing_land": "Total crop sharing land",
 "total_land_area": "Total land area",
 "total_owned_land": "Total owned land",
 "total_rented_land": "Total rented land",
 "validity_from": "Valid from",
 "validity_to": "Valid until",
 "water_source": "Water source",
 "year_of_acquisition": "Year of acquisition"
}'::jsonb)::json
WHERE "language_code" = 'en';

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(replace(section_ui_schema::text, '"panel-title": "DA Record"', '"panel-title": "DA record"'), '"section-title": "DA Record"', '"section-title": "DA record"')::jsonb
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90' AND "section_id" = 'da_record_section_00';

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(replace(replace(section_ui_schema::text, '"widget-label": "Education Level"', '"widget-label": "Education level"'), '"widget-label": "Joining Date"', '"widget-label": "Joining date"'), '"section-title": "Education & Professional"', '"section-title": "Education & professional"')::jsonb
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90' AND "section_id" = 'da_service_section_02';

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(replace(replace(replace(replace(replace(section_ui_schema::text, '"widget-label": "Father Name"', '"widget-label": "Father name"'), '"widget-label": "Grandfather Name"', '"widget-label": "Grandfather name"'), '"widget-label": "Marital Status"', '"widget-label": "Marital status"'), '"widget-label": "Month of Birth (EC)"', '"widget-label": "Month of birth (EC)"'), '"widget-label": "Year of Birth (EC)"', '"widget-label": "Year of birth (EC)"'), '"section-title": "Personal Details"', '"section-title": "Personal details"')::jsonb
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90' AND "section_id" = 'da_identity_section_01';

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(replace(replace(replace(section_ui_schema::text, '"widget-label": "Phone Number"', '"widget-label": "Phone number"'), '"widget-label": "Telegram Number"', '"widget-label": "Telegram number"'), '"widget-label": "Alternate Number"', '"widget-label": "Alternate number"'), '"section-title": "Contact Details"', '"section-title": "Contact details"')::jsonb
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90' AND "section_id" = 'da_contact_section_04';

UPDATE "public"."g2p_register_sections"
SET "section_ui_schema" = replace(replace(section_ui_schema::text, '"widget-label": "Region / Zone / Woreda / Kebele"', '"widget-label": "Region / zone / Woreda / Kebele"'), '"section-title": "Geographic Location"', '"section-title": "Geographic location"')::jsonb
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90' AND "section_id" = 'da_location_section_03';

UPDATE "public"."g2p_register_schemas"
SET "search_result_schema" = replace("search_result_schema"::jsonb::text, '"display_label": "Phone Number"', '"display_label": "Phone number"')::json
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90';

UPDATE "public"."g2p_register_schemas"
SET "filter_schema" = replace(replace(replace(replace("filter_schema"::jsonb::text, '"display_label": "Phone Number"', '"display_label": "Phone number"'), '"display_label": "Education Level"', '"display_label": "Education level"'), '"label": "Development Agent"', '"label": "Development agent"'), '"display_label": "Record Status"', '"display_label": "Record status"')::json
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90';

UPDATE "public"."g2p_register_definitions"
SET "register_subject" = 'Development agents'
WHERE "register_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90';

UPDATE "public"."g2p_intake_form_definitions"
SET "form_description" = 'DA registration'
WHERE "form_id" = '6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91';

UPDATE "public"."registry_languages"
SET "core_translation" = (COALESCE("core_translation"::jsonb, '{}'::jsonb) ||
'{
 "form_submissions": "Intake form",
 "intake_forms": "New intake",
 "search_form_submissions": "Search in intake form"
}'::jsonb)::json
WHERE "language_code" = 'en';
