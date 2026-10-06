{{ config(materialized='table', partition_by={'field': 'period_start_date', 'data_type': 'date'}, cluster_by=['partner_code', 'cmd_code']) }}

-- Direct analytics mart; basic data tests remain part of dbt build.
select
    p.*,
    h.country_value,
    h.country_count,
    h.country_coverage,
    h.hhi_raw,
    h.hhi,
    h.hhi_status
from {{ ref('int_partner_market_share') }} p
left join {{ ref('int_market_concentration_hhi') }} h
    on p.period_start_date = h.period_start_date
    and p.cmd_code = h.cmd_code and p.hs_version = h.hs_version
