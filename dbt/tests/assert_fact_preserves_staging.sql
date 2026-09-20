with s as (
    select {{ day08_source_columns() }} from {{ ref('stg_un_comtrade__partner_trades') }}
), f as (
    select {{ day08_source_columns() }} from {{ ref('fct_monthly_semiconductor_imports') }}
), missing as (select * from s except distinct select * from f),
extra as (select * from f except distinct select * from s)
select 'missing_or_changed' as issue from unnest([1]) where exists (select 1 from missing)
union all
select 'extra_or_changed' from unnest([1]) where exists (select 1 from extra)
union all
select 'row_count' from unnest([1]) where (select count(*) from s) != (select count(*) from f)
union all
select 'amount' from unnest([1]) where (select sum(primary_value) from s) is distinct from (select sum(primary_value) from f)
