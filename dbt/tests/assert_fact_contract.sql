select * from {{ ref('fct_monthly_semiconductor_imports') }}
where reporter_code is distinct from '842' or flow_code is distinct from 'M'
    or partner_code = '0' or hs_version is distinct from 'H6' or cmd_code is distinct from '8542'
    or not hs_mapping_found or not month_mapping_found
    or (not country_mapping_found and
        (partner_type != 'unknown' or classification_status != 'needs_review' or map_iso3 is not null))
