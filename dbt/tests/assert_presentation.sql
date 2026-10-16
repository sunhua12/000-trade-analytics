-- Return failures, not observations: gaps and unavailable HHI are valid data.
with partner_totals as (
    select month, cmd_code, hs_version,
        sum(import_value) as country_value, count(*) as country_count
    from {{ ref('mart_dashboard_partners') }}
    group by month, cmd_code, hs_version
)
select 'monthly_contract' as failed_check
from {{ ref('mart_dashboard_monthly') }} m
left join partner_totals p using (month, cmd_code, hs_version)
where (m.hhi_status = 'ok') != (m.hhi is not null)
    or ((m.previous_year_world_value is null or m.previous_year_world_value <= 0)
        and m.world_yoy is not null)
    or (m.world_value is null and m.world_yoy is not null)
    or m.country_count != coalesce(p.country_count, 0)
    or m.country_value is distinct from p.country_value
    or m.has_countries != (m.country_count > 0)
    or m.has_world != (m.world_value is not null)
union all
select 'partner_metric_contract' as failed_check
from {{ ref('mart_dashboard_partners') }} p
join {{ ref('mart_dashboard_monthly') }} m using (month, cmd_code, hs_version)
where p.import_value < 0
    or ((m.world_value is null or m.world_value <= 0) and p.market_share is not null)
    or (m.world_value > 0 and p.market_share is distinct from safe_divide(p.import_value, m.world_value))
    or ((p.previous_year_value is null or p.previous_year_value <= 0) and p.yoy is not null)
    or ((p.previous_month_value is null or p.previous_month_value <= 0) and p.mom is not null)
