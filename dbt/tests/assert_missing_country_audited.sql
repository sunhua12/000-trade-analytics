select s.* from {{ ref('stg_un_comtrade__partner_trades') }} s
left join {{ ref('dim_countries') }} c on s.partner_code = c.partner_code
where c.partner_code is null and not exists (
    select 1 from {{ ref('audit_partner_mapping_issues') }} a
    where a.partner_code = s.partner_code and a.period_start_date = s.period_start_date
      and a.hs_version = s.hs_version and a.cmd_code = s.cmd_code
      and a.run_id is not distinct from s.run_id
      and a.source_file is not distinct from s.source_file
      and a.issue_type = 'missing_reference'
)
