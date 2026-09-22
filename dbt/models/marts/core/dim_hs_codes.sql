{{ config(materialized='table') }}

select hs_version, cmd_code, hs_description, code_level, parent_code, source_url, retrieved_at
from {{ ref('hs_code_reference') }}
