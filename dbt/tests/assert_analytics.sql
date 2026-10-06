select 'metric_contract' as failed_check
where exists (
select period_start_date, partner_code, cmd_code, hs_version
from {{ ref('mart_us_semiconductor_supply_chain') }}
where ((world_value is null or world_value <= 0) and market_share is not null)
    or ((previous_month_value is null or previous_month_value <= 0) and mom is not null)
    or ((previous_year_value is null or previous_year_value <= 0) and yoy is not null)
    or ((net_weight is null or net_weight <= 0) and unit_value_usd_per_kg is not null)
    or (hhi_status != 'ok' and hhi is not null)
    or (hhi_status = 'ok' and hhi is null)
)
union all
select 'month_spine_complete' as failed_check
where exists (
with expected as (
    select
        month_start_date,
        format_date('%Y%m', month_start_date) as period,
        extract(year from month_start_date) as year_number,
        extract(month from month_start_date) as month_number,
        last_day(month_start_date, month) as month_end_date
    from unnest(
        generate_date_array(
            date '{{ var("month_spine_start_date") }}',
            greatest(
            date '{{ var("month_spine_end_date") }}',
            coalesce((select max(period_start_date) from {{ ref('stg_un_comtrade__partner_trades') }}), date '{{ var("month_spine_start_date") }}'),
            coalesce((select max(period_start_date) from {{ ref('stg_un_comtrade__world_totals') }}), date '{{ var("month_spine_start_date") }}')
        ),
            interval 1 month
        )
    ) as month_start_date
),

actual as (
    select
        month_start_date,
        period,
        year_number,
        month_number,
        month_end_date
    from {{ ref('dim_months') }}
),

missing_or_incorrect as (
    select * from expected
    except distinct
    select * from actual
),

unexpected as (
    select * from actual
    except distinct
    select * from expected
)

select * from missing_or_incorrect
union all
select * from unexpected
union all
select month_start_date, any_value(period), any_value(year_number),
       any_value(month_number), any_value(month_end_date)
from actual group by month_start_date having count(*) > 1
)
union all
select 'missing_country_audited' as failed_check
where exists (
select s.* from {{ ref('stg_un_comtrade__partner_trades') }} s
left join {{ ref('dim_countries') }} c on s.partner_code = c.partner_code
where c.partner_code is null and not exists (
    select 1 from {{ ref('audit_partner_mapping_issues') }} a
    where a.partner_code = s.partner_code and a.period_start_date = s.period_start_date
      and a.hs_version = s.hs_version and a.cmd_code = s.cmd_code
      and a.run_id is not distinct from s.run_id
      and a.source_file is not distinct from s.source_file
      and a.issue_type = 'missing_reference'
)
)
