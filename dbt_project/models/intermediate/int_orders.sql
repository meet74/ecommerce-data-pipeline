-- Valid orders only (no test orders, duplicates or cancellations), with the customer
-- identity resolved and every money field converted to CAD.
with orders as (
    select * from {{ ref('stg_shopify__orders') }}
    where not is_test and not is_duplicate and not is_cancelled
),

customers as (
    select customer_id, customer_key from {{ ref('stg_shopify__customers') }}
),

lines as (
    select order_id, sum(quantity) as units, count(*) as line_count
    from {{ ref('stg_shopify__order_lines') }}
    group by order_id
),

refunds as (
    select r.order_id, sum(r.amount) as refund_total
    from {{ ref('stg_shopify__refunds') }} r
    group by r.order_id
),

keyed as (
    select
        o.*,
        -- the customer record is authoritative; fall back to the order's own email for guest checkouts
        coalesce(c.customer_key, o.email_norm) as customer_key
    from orders o
    left join customers c on c.customer_id = o.customer_id
),

sequenced as (
    select
        *,
        case
            when customer_key is null then null
            else row_number() over (partition by customer_key order by created_at, order_id)
        end as order_seq
    from keyed
)

select
    s.order_id,
    s.order_number,
    s.created_at,
    cast(s.created_at as date) as order_date,
    s.customer_key,
    s.order_seq,
    case
        when s.customer_key is null then 'guest'
        when s.order_seq = 1 then 'new'
        else 'returning'
    end as customer_type,
    s.currency,
    s.financial_status,
    s.discount_code,
    s.shipping_country,
    fx.cad_per_unit as fx_rate_cad,
    s.subtotal_price as subtotal,
    s.total_discounts as discounts,
    s.total_shipping_price as shipping,
    s.total_tax as tax,
    s.total_price as total,
    (s.total_price - s.total_tax) * fx.cad_per_unit as revenue_cad,
    s.total_discounts * fx.cad_per_unit as discounts_cad,
    coalesce(l.units, 0) as units,
    coalesce(l.line_count, 0) as line_count,
    coalesce(r.refund_total, 0) as refund_total,
    case when r.order_id is not null then 1 else 0 end as has_refund
from sequenced s
left join lines l on l.order_id = s.order_id
left join refunds r on r.order_id = s.order_id
left join {{ ref('int_fx_daily') }} fx on fx.date_day = cast(s.created_at as date) and fx.currency = s.currency
