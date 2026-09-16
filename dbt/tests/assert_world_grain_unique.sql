select
    period_start_date,
    cmd_code,
    hs_version,
    count(*) as row_count
from {{ ref('stg_un_comtrade__world_totals') }}
group by 1, 2, 3
having count(*) > 1
