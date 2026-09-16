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
        date '2023-01-01',
        date '2024-12-01',
        interval 1 month
    )
) as month_start_date
