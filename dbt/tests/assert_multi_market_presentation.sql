-- Metric ownership lives here; Python validates only the transport contract.
with monthly as (
    select * from {{ ref('mart_multi_market_ic_monthly') }}
), partners as (
    select * from {{ ref('mart_multi_market_ic_partners') }}
), totals as (
    select reporter_code, cmd_code, month, sum(import_value) country_value,
        count(*) country_count, sum(pow(cast(market_share as float64) * 100, 2)) hhi
    from partners group by 1, 2, 3
)
select 'monthly_contract' failed_check
from monthly m left join totals t using (reporter_code, cmd_code, month)
left join monthly y on m.reporter_code = y.reporter_code and m.cmd_code = y.cmd_code
    and y.month = date_sub(m.month, interval 1 year)
where m.country_count != coalesce(t.country_count, 0)
    or m.country_value is distinct from t.country_value
    or m.has_world != (m.world_value is not null)
    or m.has_countries != (coalesce(t.country_count, 0) > 0)
    or m.world_value < 0 or m.country_value < 0
    or m.previous_year_world_value is distinct from y.world_value
    or m.world_yoy is distinct from
        case when m.previous_year_world_value > 0
            then safe_divide(m.world_value, m.previous_year_world_value) - 1 end
    or m.country_coverage is distinct from
        case when m.world_value > 0 then safe_divide(m.country_value, m.world_value) end
    or (m.hhi_status = 'ok') != (m.hhi is not null)
    or (m.hhi is not null and (m.country_coverage is null
        or abs(1 - m.country_coverage) > 0.005 or abs(m.hhi - t.hhi) > 0.0001))
union all
select 'partner_contract' failed_check
from partners p join monthly m using (reporter_code, cmd_code, month)
left join partners prev on p.reporter_code = prev.reporter_code and p.cmd_code = prev.cmd_code
    and p.partner_code = prev.partner_code and prev.month = date_sub(p.month, interval 1 month)
left join partners y on p.reporter_code = y.reporter_code and p.cmd_code = y.cmd_code
    and p.partner_code = y.partner_code and y.month = date_sub(p.month, interval 1 year)
where p.import_value < 0
    or p.previous_month_value is distinct from prev.import_value
    or p.previous_year_value is distinct from y.import_value
    or p.market_share is distinct from
        case when m.world_value > 0 then safe_divide(p.import_value, m.world_value) end
    or p.market_share_status != case when m.world_value is null then 'missing_world'
        when m.world_value <= 0 then 'invalid_world' else 'ok' end
    or p.mom is distinct from case when p.previous_month_value > 0
        then safe_divide(p.import_value, p.previous_month_value) - 1 end
    or p.yoy is distinct from case when p.previous_year_value > 0
        then safe_divide(p.import_value, p.previous_year_value) - 1 end
