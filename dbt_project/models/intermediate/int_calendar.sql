-- One row per calendar day from the first order to the latest event. Recursive CTE so it
-- runs unchanged on DuckDB and Postgres.
with recursive bounds as (
    select
        cast(min(created_at) as date) as first_day,
        cast(max(created_at) as date) as last_day
    from (
        select created_at from {{ ref('stg_shopify__orders') }}
        union all
        select created_at from {{ ref('stg_shopify__refunds') }}
        union all
        select created_at from {{ ref('stg_stripe__charges') }}
    ) events
),

spine as (
    select first_day as date_day, last_day from bounds
    union all
    select cast(date_day + interval '1 day' as date), last_day from spine where date_day < last_day
)

select date_day from spine
