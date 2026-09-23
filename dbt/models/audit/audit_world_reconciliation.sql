{{ config(materialized='view', enabled=var('enable_publication_audit', false)) }}

-- History is owned by the publisher; dbt full-refresh can only rebuild this view.
select * from {{ source('publication', 'audit_world_reconciliation') }}
