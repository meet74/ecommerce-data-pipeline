-- One row per person. Duplicate customer records (same email, different casing or spacing)
-- collapse into the oldest id; guest buyers without an account are included.
with keys as (
    select customer_key from {{ ref('stg_shopify__customers') }}
    union
    select customer_key from {{ ref('int_orders') }} where customer_key is not null
),

profile as (
    select
        customer_key,
        customer_id,
        email_norm,
        first_name,
        last_name,
        country,
        accepts_marketing,
        created_at as signup_at
    from {{ ref('stg_shopify__customers') }}
    where not is_duplicate
),

activity as (
    select
        customer_key,
        min(created_at) as first_order_at,
        max(created_at) as last_order_at,
        count(*) as orders,
        sum(units) as units,
        sum(revenue_cad) as lifetime_revenue_cad,
        sum(net_revenue_cad) as lifetime_net_revenue_cad
    from {{ ref('fct_orders') }}
    where customer_key is not null
    group by customer_key
),

dups as (
    select customer_key, count(*) as source_record_count
    from {{ ref('stg_shopify__customers') }}
    group by customer_key
)

select
    k.customer_key,
    p.customer_id,
    coalesce(p.email_norm, case when k.customer_key like 'id:%' then null else k.customer_key end) as email,
    p.first_name,
    p.last_name,
    p.country,
    coalesce(p.accepts_marketing, false) as accepts_marketing,
    p.signup_at,
    a.first_order_at,
    a.last_order_at,
    coalesce(a.orders, 0) as orders,
    coalesce(a.units, 0) as units,
    coalesce(a.lifetime_revenue_cad, 0) as lifetime_revenue_cad,
    coalesce(a.lifetime_net_revenue_cad, 0) as lifetime_net_revenue_cad,
    case
        when coalesce(a.orders, 0) = 0 then 'prospect'
        when a.orders = 1 then 'one_time'
        else 'repeat'
    end as segment,
    coalesce(d.source_record_count, 1) as source_record_count
from keys k
left join profile p on p.customer_key = k.customer_key
left join activity a on a.customer_key = k.customer_key
left join dups d on d.customer_key = k.customer_key
