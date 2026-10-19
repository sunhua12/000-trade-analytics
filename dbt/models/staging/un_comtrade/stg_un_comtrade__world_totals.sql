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
 from {{ source('un_comtrade', 'world_total') }}
where period_start_date >= date '{{ var("raw_start_date") }}'
  and period_start_date < date '{{ var("raw_end_date") }}'

-- Preserve the original dashboard contract during the v2 rollout.
and reporter_code = '842' and cmd_code = '8542' and hs_version = 'H6'
