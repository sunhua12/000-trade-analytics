{% macro day08_source_columns(alias="") %}
{{ alias }}period,
{{ alias }}period_start_date,
{{ alias }}reporter_code,
{{ alias }}partner_code,
{{ alias }}flow_code,
{{ alias }}cmd_code,
{{ alias }}hs_version,
{{ alias }}primary_value,
{{ alias }}net_weight,
{{ alias }}quantity,
{{ alias }}ingested_at,
{{ alias }}source_file,
{{ alias }}checksum,
{{ alias }}run_id,
{{ alias }}revision
{% endmacro %}
