-- Line items of valid orders in CAD, with each order's refund spread over its lines pro rata.
with order_totals as (
    select order_id, sum(line_net) as lines_net
    from {{ ref('stg_shopify__order_lines') }}
    group by order_id
),

order_refunds as (
    select order_id, sum(refund_ex_tax_cad) as refund_ex_tax_cad
    from {{ ref('int_refunds') }}
    group by order_id
)

select
    l.line_id,
    l.order_id,
    l.product_id,
    o.order_date,
    l.quantity,
    l.line_net,
    l.line_net * o.fx_rate_cad as line_net_cad,
    coalesce(rf.refund_ex_tax_cad, 0) * l.line_net / nullif(t.lines_net, 0) as refund_alloc_cad
from {{ ref('stg_shopify__order_lines') }} l
inner join {{ ref('int_orders') }} o on o.order_id = l.order_id
inner join order_totals t on t.order_id = l.order_id
left join order_refunds rf on rf.order_id = l.order_id
