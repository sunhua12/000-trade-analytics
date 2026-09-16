select
    period_start_date,
    partner_code,
    cmd_code,
    hs_version,
    count(*) as row_count
from {{ ref('stg_un_comtrade__partner_trades') }}
group by 1, 2, 3, 4
having count(*) > 1
