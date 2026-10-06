select 'staging_contract' as failed_check
where exists (
with combined as (
    select
        'partner_detail' as source_type,
        period,
        period_start_date,
        reporter_code,
        partner_code,
        flow_code,
        cmd_code,
        hs_version,
        primary_value,
        ingested_at,
        source_file,
        checksum,
        run_id,
        revision
    from {{ ref('stg_un_comtrade__partner_trades') }}

    union all

    select
        'world_total' as source_type,
        period,
        period_start_date,
        reporter_code,
        partner_code,
        flow_code,
        cmd_code,
        hs_version,
        primary_value,
        ingested_at,
        source_file,
        checksum,
        run_id,
        revision
    from {{ ref('stg_un_comtrade__world_totals') }}
)

select * except (grain_count)
from (
    select *, count(*) over (
        partition by source_type, period_start_date, partner_code, cmd_code, hs_version
    ) as grain_count
    from combined
)
where grain_count > 1 or
    -- 必要欄位不可為 NULL
    period is null
    or period_start_date is null
    or reporter_code is null
    or partner_code is null
    or flow_code is null
    or cmd_code is null
    or hs_version is null
    or primary_value is null
    or ingested_at is null
    or source_file is null
    or checksum is null
    or run_id is null
    or revision is null

    -- 本專案的固定來源契約
    or reporter_code != '842'
    or flow_code != 'M'
    or cmd_code != '8542'
    or hs_version != 'H6'
    or revision <= 0
    or revision != trunc(revision)

    -- 日期應為月初，且與月份代碼一致
    or period != format_date('%Y%m', period_start_date)
    or period_start_date != date_trunc(period_start_date, month)

    -- 明細排除 World，金額允許為零
    or (
        source_type = 'partner_detail'
        and (partner_code = '0' or primary_value < 0)
    )

    -- World 的 partner 固定為 0，金額必須大於零
    or (
        source_type = 'world_total'
        and (partner_code != '0' or primary_value <= 0)
    )
)
union all
select 'fact_preserves_staging' as failed_check
where exists (
with s as (
    select {{ source_columns() }} from {{ ref('stg_un_comtrade__partner_trades') }}
), f as (
    select {{ source_columns() }} from {{ ref('fct_monthly_semiconductor_imports') }}
), missing as (select * from s except distinct select * from f),
extra as (select * from f except distinct select * from s)
select 'missing_or_changed' as issue from unnest([1]) where exists (select 1 from missing)
union all
select 'extra_or_changed' from unnest([1]) where exists (select 1 from extra)
union all
select 'row_count' from unnest([1]) where (select count(*) from s) != (select count(*) from f)
union all
select 'amount' from unnest([1]) where (select sum(primary_value) from s) is distinct from (select sum(primary_value) from f)
)
union all
select 'mart_preserves_fact' as failed_check
where exists (
-- Both directions retain values and lineage; compound_unique separately guards fanout.
with original as (
    select {{ source_columns() }}
    from {{ ref('fct_monthly_semiconductor_imports') }}
), mart as (
    select {{ source_columns() }}
    from {{ ref('mart_us_semiconductor_supply_chain') }}
)
(select * from original except distinct select * from mart)
union all
(select * from mart except distinct select * from original)
)
