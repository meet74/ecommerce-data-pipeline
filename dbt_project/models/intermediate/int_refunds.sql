-- Store refunds on valid orders, converted at the refund date. The tax share of the
-- order is stripped so refunds are comparable with revenue, which excludes tax.
select
    r.refund_id,
    r.order_id,
    r.created_at,
    cast(r.created_at as date) as refund_date,
    r.currency,
    r.amount,
    r.amount * fx.cad_per_unit as refund_cad,
    r.amount * (1 - o.tax / nullif(o.total, 0)) * fx.cad_per_unit as refund_ex_tax_cad
from {{ ref('stg_shopify__refunds') }} r
inner join {{ ref('int_orders') }} o on o.order_id = r.order_id
left join {{ ref('int_fx_daily') }} fx on fx.date_day = cast(r.created_at as date) and fx.currency = r.currency
