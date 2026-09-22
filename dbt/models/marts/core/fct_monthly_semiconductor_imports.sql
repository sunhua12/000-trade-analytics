{{ config(materialized='table') }}

select
    {{ day08_source_columns('s.') }},
    c.source_name,
    coalesce(c.partner_type, 'unknown') as partner_type,
    coalesce(c.classification_status, 'needs_review') as classification_status,
    c.map_iso3,
    coalesce(c.reconciliation_role, 'unresolved') as reconciliation_role,
    h.hs_description,
    c.partner_code is not null as country_mapping_found,
    h.cmd_code is not null as hs_mapping_found,
    m.month_start_date is not null as month_mapping_found
from {{ ref('stg_un_comtrade__partner_trades') }} s
left join {{ ref('dim_countries') }} c on s.partner_code = c.partner_code
left join {{ ref('dim_hs_codes') }} h
    on s.hs_version = h.hs_version and s.cmd_code = h.cmd_code
left join {{ ref('dim_months') }} m on s.period_start_date = m.month_start_date
