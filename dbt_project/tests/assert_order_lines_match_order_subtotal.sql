-- Line items (after line discounts) must add up to the order subtotal.
select o.order_id, o.subtotal_price, l.lines_net
from {{ ref('stg_shopify__orders') }} o
inner join (
    select order_id, sum(line_net) as lines_net
    from {{ ref('stg_shopify__order_lines') }}
    group by order_id
) l on l.order_id = o.order_id
where not o.is_test and abs(o.subtotal_price - l.lines_net) > 0.01
