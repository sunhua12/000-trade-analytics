{{ config(materialized='view') }}

-- No month-grain World or HHI fields are repeated on partner rows.
select
    period_start_date as month,
    cmd_code,
    hs_version,
    partner_code,
    source_name,
    map_iso3,
    primary_value as import_value,
    market_share,
    market_share_status,
    previous_month_value,
    previous_year_value,
    mom,
    yoy
from {{ ref('int_partner_market_share') }}
where partner_type = 'country' and classification_status = 'verified'
    and cmd_code = '8542' and hs_version = 'H6'
