with counts as (
    select
        'partner_detail' as source_name,
        count(*) as row_count
    from {{ ref('stg_un_comtrade__partner_trades') }}
    where period_start_date >= date '2023-01-01'
      and period_start_date < date '2023-02-01'

    union all

    select
        'world_total' as source_name,
        count(*) as row_count
    from {{ ref('stg_un_comtrade__world_totals') }}
    where period_start_date >= date '2023-01-01'
      and period_start_date < date '2023-02-01'
)

select *
from counts
where (source_name = 'partner_detail' and row_count = 0)
   or (source_name = 'world_total' and row_count != 1)
