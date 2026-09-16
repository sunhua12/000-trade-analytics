with expected as (
    select
        month_start_date,
        format_date('%Y%m', month_start_date) as period,
        extract(year from month_start_date) as year_number,
        extract(month from month_start_date) as month_number,
        last_day(month_start_date, month) as month_end_date
    from unnest(
        generate_date_array(
            date '2023-01-01',
            date '2024-12-01',
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
