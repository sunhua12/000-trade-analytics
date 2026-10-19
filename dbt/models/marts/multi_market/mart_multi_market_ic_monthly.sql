{{ config(materialized='view') }}
with countries as (
    select period_start_date, reporter_code, cmd_code,
        max(hs_version) as hs_version,
        sum(primary_value) as country_value, count(*) as country_count,
        sum(power(cast(primary_value as float64),2)) as sum_squares
    from {{ ref('fct_multi_market_ic_imports') }}
    group by 1,2,3
), world as (
    select * from {{ source('un_comtrade', 'world_total') }}
    where period_start_date >= date '2016-01-01' and flow_code = 'M'
      and partner_code = '0'
      and cmd_code in ('854231','854232','854233','854239','854290')
    qualify row_number() over (
        partition by period_start_date, reporter_code, cmd_code, flow_code
        order by revision desc, ingested_at desc, hs_version desc
    ) = 1
), scopes as (
    select reporter_code, cmd_code from countries
    union distinct select reporter_code, cmd_code from world
), spine as (
    select month, reporter_code, cmd_code from scopes
    cross join unnest(generate_date_array(
        date '{{ var("multi_market_start_date", "2016-01-01") }}',
        date '{{ var("multi_market_end_date", "2026-09-01") }}', interval 1 month)) month
), totals as (
    select s.*, coalesce(w.hs_version,c.hs_version) as hs_version,
        w.primary_value as world_value,
        c.country_value, coalesce(c.country_count,0) as country_count,
        safe_divide(c.country_value,nullif(w.primary_value,0)) as country_coverage,
        safe_divide(c.sum_squares,power(cast(nullif(w.primary_value,0) as float64),2))*10000 as raw_hhi
    from spine s
    left join world w on s.month=w.period_start_date
      and s.reporter_code=w.reporter_code and s.cmd_code=w.cmd_code
    left join countries c on s.month=c.period_start_date
      and s.reporter_code=c.reporter_code and s.cmd_code=c.cmd_code
), metrics as (
    select *, case
        when world_value is null then 'missing_world'
        when world_value <= 0 then 'invalid_world'
        when country_count = 0 then 'no_countries'
        when abs(country_coverage-1) > 0.005 then 'insufficient_coverage'
        else 'ok' end as hhi_status
    from totals
)
select t.* except(raw_hhi), py.world_value as previous_year_world_value,
    case when py.world_value > 0 then safe_divide(t.world_value,py.world_value)-1 end as world_yoy,
    t.world_value is not null as has_world, t.country_count > 0 as has_countries,
    case when t.hhi_status='ok' then cast(t.raw_hhi as numeric) end as hhi
from metrics t left join metrics py
  on py.month=date_sub(t.month, interval 1 year)
  and t.reporter_code=py.reporter_code and t.cmd_code=py.cmd_code
