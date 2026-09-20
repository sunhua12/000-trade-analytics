{{ config(materialized='table') }}

with mapped as (
    select s.run_id, s.period_start_date, s.cmd_code, s.hs_version,
        s.partner_code, s.primary_value, s.source_file,
        c.partner_code is null as missing_reference,
        coalesce(c.classification_status, 'needs_review') != 'verified' as classification_needs_review,
        coalesce(c.reconciliation_role, 'unresolved') = 'unresolved' as reconciliation_unresolved,
        c.map_iso3 is null as map_unavailable,
        c.classification_note, c.mapping_note
    from {{ ref('stg_un_comtrade__partner_trades') }} s
    left join {{ ref('dim_countries') }} c on s.partner_code = c.partner_code
), issues as (
    {% for issue in ['missing_reference', 'classification_needs_review', 'reconciliation_unresolved', 'map_unavailable'] %}
    select *, '{{ issue }}' as issue_type,
        {% if issue == 'missing_reference' %}'No reference for source partner_code'
        {% elif issue == 'map_unavailable' %}coalesce(mapping_note, 'No verified map mapping')
        {% else %}coalesce(classification_note, 'No reviewed classification'){% endif %} as reason
    from mapped where {{ issue }}
    {% if not loop.last %}union all{% endif %}
    {% endfor %}
)
select timestamp('{{ run_started_at.isoformat() }}') as observed_at,
    run_id, period_start_date, cmd_code, hs_version, partner_code, issue_type,
    source_file, reason, count(*) as row_count, sum(primary_value) as primary_value_sum
from issues
group by run_id, period_start_date, cmd_code, hs_version, partner_code,
    issue_type, source_file, reason
