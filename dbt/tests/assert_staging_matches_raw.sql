{% set columns %}
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
{% endset %}

{% set pairs = [
    ('partner_detail', 'stg_un_comtrade__partner_trades'),
    ('world_total', 'stg_un_comtrade__world_totals')
] %}

with
{% for source_name, model_name in pairs %}
raw_{{ source_name }} as (
    select {{ columns }}
    from {{ source('un_comtrade', source_name) }}
    where period_start_date >= date '2023-01-01'
      and period_start_date < date '2023-02-01'
),

staging_{{ source_name }} as (
    select {{ columns }}
    from {{ ref(model_name) }}
    where period_start_date >= date '2023-01-01'
      and period_start_date < date '2023-02-01'
),

missing_{{ source_name }} as (
    select * from raw_{{ source_name }}
    except distinct
    select * from staging_{{ source_name }}
),

unexpected_{{ source_name }} as (
    select * from staging_{{ source_name }}
    except distinct
    select * from raw_{{ source_name }}
),

checks_{{ source_name }} as (
    select
        '{{ source_name }}' as source_name,
        'raw_rows_missing_or_changed' as check_name,
        count(*) as failure_count
    from missing_{{ source_name }}

    union all

    select
        '{{ source_name }}',
        'staging_rows_extra_or_changed',
        count(*)
    from unexpected_{{ source_name }}

    union all

    select
        '{{ source_name }}',
        'row_count_difference',
        abs(
            (select count(*) from raw_{{ source_name }})
            - (select count(*) from staging_{{ source_name }})
        )
)
{% if not loop.last %},{% endif %}
{% endfor %}

{% for source_name, model_name in pairs %}
select *
from checks_{{ source_name }}
where failure_count > 0
{% if not loop.last %}
union all
{% endif %}
{% endfor %}
