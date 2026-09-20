{{ config(materialized='table') }}

select
    partner_code,
    source_name,
    source_note,
    source_iso_alpha3,
    source_is_group,
    partner_type,
    classification_status,
    nullif(map_iso3, '') as map_iso3,
    reconciliation_role,
    source_url,
    retrieved_at,
    classification_source_url,
    classification_note,
    mapping_source_url,
    mapping_note
from {{ ref('country_reference') }}
