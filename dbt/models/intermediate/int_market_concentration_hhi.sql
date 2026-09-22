{{ config(materialized='view') }}

with country_totals as (
    select
        period_start_date, cmd_code, hs_version,
        countif(partner_type = 'country') as country_count,
        countif(partner_type = 'country' and primary_value is null) as missing_country_values,
        countif(partner_type = 'country' and primary_value < 0) as negative_country_values,
        countif(partner_type = 'country' and coalesce(classification_status, '') != 'verified')
            as unreviewed_countries,
        sum(case when partner_type = 'country' then primary_value end) as country_value,
        sum(case when partner_type = 'country' then power(market_share * 100, 2) end) as hhi_raw
    from {{ ref('int_partner_market_share') }}
    group by period_start_date, cmd_code, hs_version
), coverage as (
    -- FULL JOIN also exposes World-only months and detail without a World denominator.
    select
        coalesce(c.period_start_date, w.period_start_date) as period_start_date,
        coalesce(c.cmd_code, w.cmd_code) as cmd_code,
        coalesce(c.hs_version, w.hs_version) as hs_version,
        w.primary_value as world_value,
        c.country_value,
        coalesce(c.country_count, 0) as country_count,
        coalesce(c.missing_country_values, 0) as missing_country_values,
        coalesce(c.negative_country_values, 0) as negative_country_values,
        coalesce(c.unreviewed_countries, 0) as unreviewed_countries,
        c.hhi_raw,
        case when w.primary_value > 0
            then safe_divide(c.country_value, w.primary_value) end as country_coverage
    from country_totals c
    full outer join {{ ref('stg_un_comtrade__world_totals') }} w
        on c.period_start_date = w.period_start_date
        and c.cmd_code = w.cmd_code and c.hs_version = w.hs_version
), classified as (
    select *,
        case
            when world_value is null then 'missing_world'
            when world_value <= 0 then 'invalid_world'
            when country_count = 0 then 'no_countries'
            when missing_country_values > 0 then 'missing_country_value'
            when negative_country_values > 0 then 'negative_country_value'
            when unreviewed_countries > 0 then 'unreviewed_country'
            when abs(1 - country_coverage) > {{ var('hhi_coverage_tolerance', 0.005) }}
                then 'insufficient_coverage'
            else 'ok'
        end as hhi_status
    from coverage
)
select *,
    case when hhi_status = 'ok' then hhi_raw end as hhi
from classified
