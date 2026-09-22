{{ config(materialized='table') }}

-- Candidate only: Day 10 owns the reconciliation gate and publication.
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
