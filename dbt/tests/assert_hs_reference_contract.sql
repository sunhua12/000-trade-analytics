select * from {{ ref('dim_hs_codes') }}
where code_level != 4 or length(cmd_code) != code_level
union all
select * from {{ ref('dim_hs_codes') }} where hs_version = 'H6' and cmd_code != '8542'
