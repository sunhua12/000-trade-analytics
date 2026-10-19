{{ config(materialized='view') }}
select f.period_start_date as month, f.reporter_code, f.cmd_code, f.hs_version,
    f.partner_code, f.source_name, f.map_iso3, f.primary_value as import_value,
    case when w.world_value > 0 then safe_divide(f.primary_value,w.world_value) end as market_share,
    case when w.world_value is null then 'missing_world'
         when w.world_value <= 0 then 'invalid_world' else 'ok' end as market_share_status,
    pm.primary_value as previous_month_value, py.primary_value as previous_year_value,
    case when pm.primary_value > 0 then safe_divide(f.primary_value,pm.primary_value)-1 end as mom,
    case when py.primary_value > 0 then safe_divide(f.primary_value,py.primary_value)-1 end as yoy
from {{ ref('fct_multi_market_ic_imports') }} f
left join {{ ref('mart_multi_market_ic_monthly') }} w
  on f.period_start_date=w.month and f.reporter_code=w.reporter_code and f.cmd_code=w.cmd_code
left join {{ ref('fct_multi_market_ic_imports') }} pm
  on pm.period_start_date=date_sub(f.period_start_date,interval 1 month)
  and f.reporter_code=pm.reporter_code and f.cmd_code=pm.cmd_code and f.partner_code=pm.partner_code
left join {{ ref('fct_multi_market_ic_imports') }} py
  on py.period_start_date=date_sub(f.period_start_date,interval 1 year)
  and f.reporter_code=py.reporter_code and f.cmd_code=py.cmd_code and f.partner_code=py.partner_code
