{{ config(materialized='view') }}

-- Month spine preserves absent detail, World-only months, and complete gaps.
select
    m.month_start_date as month,
    d.cmd_code,
    d.hs_version,
    w.primary_value as world_value,
    py.primary_value as previous_year_world_value,
    case when py.primary_value > 0
        then safe_divide(w.primary_value, py.primary_value) - 1 end as world_yoy,
    h.country_value,
    coalesce(h.country_count, 0) as country_count,
    h.country_coverage,
    -- HHI originates in POWER (FLOAT64); normalize display precision explicitly.
    cast(h.hhi as numeric) as hhi,
    coalesce(h.hhi_status, 'missing_world') as hhi_status,
    w.period_start_date is not null as has_world,
    coalesce(h.country_count, 0) > 0 as has_countries
from {{ ref('dim_months') }} m
cross join {{ ref('dim_hs_codes') }} d
left join {{ ref('stg_un_comtrade__world_totals') }} w
    on m.month_start_date = w.period_start_date
    and d.cmd_code = w.cmd_code and d.hs_version = w.hs_version
left join {{ ref('stg_un_comtrade__world_totals') }} py
    on py.period_start_date = date_sub(m.month_start_date, interval 1 year)
    and d.cmd_code = py.cmd_code and d.hs_version = py.hs_version
left join {{ ref('int_market_concentration_hhi') }} h
    on m.month_start_date = h.period_start_date
    and d.cmd_code = h.cmd_code and d.hs_version = h.hs_version
where d.cmd_code = '8542' and d.hs_version = 'H6'
