{{ config(materialized='view') }}

-- Calendar joins preserve missing periods; a previous row is not necessarily last month.
select
    f.*,
    w.primary_value as world_value,
    case when w.primary_value > 0
        then safe_divide(f.primary_value, w.primary_value) end as market_share,
    case
        when w.primary_value is null then 'missing_world'
        when w.primary_value <= 0 then 'invalid_world'
        when f.primary_value is null then 'missing_value'
        else 'ok'
    end as market_share_status,
    pm.primary_value as previous_month_value,
    py.primary_value as previous_year_value,
    case when pm.primary_value > 0
        then safe_divide(f.primary_value, pm.primary_value) - 1 end as mom,
    case when py.primary_value > 0
        then safe_divide(f.primary_value, py.primary_value) - 1 end as yoy,
    case when f.net_weight > 0
        then safe_divide(f.primary_value, f.net_weight) end as unit_value_usd_per_kg
from {{ ref('fct_monthly_semiconductor_imports') }} f
left join {{ ref('stg_un_comtrade__world_totals') }} w
    on f.period_start_date = w.period_start_date
    and f.cmd_code = w.cmd_code and f.hs_version = w.hs_version
left join {{ ref('fct_monthly_semiconductor_imports') }} pm
    on pm.period_start_date = date_sub(f.period_start_date, interval 1 month)
    and f.partner_code = pm.partner_code
    and f.cmd_code = pm.cmd_code and f.hs_version = pm.hs_version
left join {{ ref('fct_monthly_semiconductor_imports') }} py
    on py.period_start_date = date_sub(f.period_start_date, interval 1 year)
    and f.partner_code = py.partner_code
    and f.cmd_code = py.cmd_code and f.hs_version = py.hs_version
