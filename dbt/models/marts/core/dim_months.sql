{{ config(materialized='table') }}

select
    month_start_date,
    format_date('%Y%m', month_start_date) as period,
    extract(year from month_start_date) as year_number,
    extract(month from month_start_date) as month_number,
    date_sub(
        date_add(month_start_date, interval 1 month),
        interval 1 day
    ) as month_end_date
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
