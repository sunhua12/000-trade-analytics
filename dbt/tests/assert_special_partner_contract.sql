select * from {{ ref('dim_countries') }}
where (partner_code = '490' and (partner_type != 'special' or map_iso3 is not null
    or reconciliation_role != 'detail' or source_name != 'Other Asia, nes'))
    or (partner_code = '0' and (partner_type != 'world' or reconciliation_role != 'world'))
    or map_iso3 = 'NULL'
