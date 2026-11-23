-- One row per valid order. Revenue excludes tax and is in CAD at the order-date rate.
-- Refunds are attributed to the order here; daily_kpis re-attributes them to the refund date.
with refunds as (
    select order_id, sum(refund_ex_tax_cad) as refund_ex_tax_cad
    from {{ ref('int_refunds') }}
    group by order_id
),

fees as (
    select order_id, sum(fee_cad) as fees_cad, count(*) as charge_count
    from {{ ref('int_charges') }}
    where order_id is not null
    group by order_id
)

select
    o.order_id,
    o.order_number,
    o.created_at,
    o.order_date,
    o.customer_key,
    o.customer_type,
    o.order_seq,
    o.currency,
    o.fx_rate_cad,
    o.financial_status,
    o.discount_code,
    o.shipping_country,
    o.subtotal,
    o.discounts,
    o.shipping,
    o.tax,
    o.total,
    o.units,
    o.line_count,
    o.has_refund,
    o.refund_total,
    o.revenue_cad,
    o.discounts_cad,
    coalesce(r.refund_ex_tax_cad, 0) as refund_ex_tax_cad,
    coalesce(f.fees_cad, 0) as fees_cad,
    coalesce(f.charge_count, 0) as charge_count,
    o.revenue_cad - coalesce(r.refund_ex_tax_cad, 0) - coalesce(f.fees_cad, 0) as net_revenue_cad
from {{ ref('int_orders') }} o
left join refunds r on r.order_id = o.order_id
left join fees f on f.order_id = o.order_id
