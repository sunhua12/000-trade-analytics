{{ config(materialized='view') }}

select
    period,
    period_start_date,
    reporter_code,
    partner_code,
    flow_code,
    cmd_code,
    hs_version,
    primary_value,
    net_weight,
    quantity,
    ingested_at,
    source_file,
    checksum,
    run_id,
    revision
from {{ source('un_comtrade', 'partner_detail') }}
where period_start_date >= date '{{ var("raw_start_date") }}'
  and period_start_date < date '{{ var("raw_end_date") }}'
