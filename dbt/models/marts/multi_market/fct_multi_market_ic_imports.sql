{{ config(materialized='incremental', incremental_strategy='insert_overwrite',
    on_schema_change='append_new_columns',
    partition_by={'field':'period_start_date','data_type':'date'},
    cluster_by=['reporter_code','cmd_code','partner_code']) }}

{% set refresh_periods = var('multi_market_refresh_periods', none) %}
-- Select a complete accepted extract, then replace only affected month partitions.
-- Selecting revisions by partner would retain partners removed by a newer extract.
with accepted_source as (
    select r.*
    from {{ source('un_comtrade', 'partner_detail') }} r
    where r.period_start_date >= date '2016-01-01'
      and r.flow_code = 'M'
      and r.cmd_code in ('854231','854232','854233','854239','854290')
    {% if is_incremental() %}
        {% if refresh_periods is not none %}
            {% if refresh_periods | length > 0 %}
      and r.period_start_date in (
                {% for period in refresh_periods %}
          date '{{ period[:4] }}-{{ period[4:] }}-01'{% if not loop.last %},{% endif %}
                {% endfor %}
      )
            {% else %}
      and false
            {% endif %}
        {% else %}
      and r.period_start_date in (
          select distinct period_start_date
          from {{ source('un_comtrade', 'partner_detail') }}
          where period_start_date >= date '2016-01-01'
            and ingested_at >= (
                select coalesce(max(ingested_at),timestamp '1970-01-01') from {{ this }}
            )
      )
        {% endif %}
    {% endif %}
    qualify dense_rank() over (
        partition by r.period_start_date,r.reporter_code,r.cmd_code,r.flow_code
        order by r.revision desc,r.ingested_at desc,r.hs_version desc,r.source_file desc
    ) = 1
)
select r.*, c.source_name, c.map_iso3, h.hs_description,
    h.cmd_code is not null as hs_mapping_found
from accepted_source r
join {{ ref('dim_countries') }} c on r.partner_code=c.partner_code
left join {{ ref('dim_hs_codes') }} h
  on r.cmd_code=h.cmd_code and r.hs_version=h.hs_version
where c.partner_type='country' and c.classification_status='verified'
  and r.primary_value is not null and r.primary_value >= 0
