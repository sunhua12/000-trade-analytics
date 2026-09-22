-- Both directions retain values and lineage; compound_unique separately guards fanout.
with original as (
    select {{ day08_source_columns() }}
    from {{ ref('fct_monthly_semiconductor_imports') }}
), candidate as (
    select {{ day08_source_columns() }}
    from {{ ref('mart_us_semiconductor_supply_chain_candidate') }}
)
(select * from original except distinct select * from candidate)
union all
(select * from candidate except distinct select * from original)
