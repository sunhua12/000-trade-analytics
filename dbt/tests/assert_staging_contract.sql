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

select *
from combined
where
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
