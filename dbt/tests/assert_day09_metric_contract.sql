select period_start_date, partner_code, cmd_code, hs_version
from {{ ref('mart_us_semiconductor_supply_chain_candidate') }}
where ((world_value is null or world_value <= 0) and market_share is not null)
    or ((previous_month_value is null or previous_month_value <= 0) and mom is not null)
    or ((previous_year_value is null or previous_year_value <= 0) and yoy is not null)
    or ((net_weight is null or net_weight <= 0) and unit_value_usd_per_kg is not null)
    or (hhi_status != 'ok' and hhi is not null)
    or (hhi_status = 'ok' and hhi is null)
