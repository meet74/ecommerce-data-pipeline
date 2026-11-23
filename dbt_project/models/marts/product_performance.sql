-- Per product, over all valid orders. Cost is the catalogue unit cost in CAD, so margin
-- uses it as-is for USD orders too. Refunds are allocated to lines pro rata.
with sales as (
    select
        product_id,
        count(distinct order_id) as orders,
        sum(quantity) as units_sold,
        sum(line_net_cad) as revenue_cad,
        sum(refund_alloc_cad) as refunds_cad
    from {{ ref('int_order_lines') }}
    group by product_id
)

select
    p.product_id,
    p.title,
    p.product_type,
    p.sku,
    p.status,
    coalesce(s.orders, 0) as orders,
    coalesce(s.units_sold, 0) as units_sold,
    cast(coalesce(s.revenue_cad, 0) as numeric(16, 2)) as revenue_cad,
    cast(coalesce(s.refunds_cad, 0) as numeric(16, 2)) as refunds_cad,
    cast(coalesce(s.revenue_cad, 0) - coalesce(s.refunds_cad, 0) as numeric(16, 2)) as net_revenue_cad,
    cast(coalesce(s.units_sold, 0) * p.unit_cost as numeric(16, 2)) as cogs_cad,
    cast(coalesce(s.revenue_cad, 0) - coalesce(s.refunds_cad, 0) - coalesce(s.units_sold, 0) * p.unit_cost as numeric(16, 2)) as gross_margin_cad,
    cast(1.0 * (coalesce(s.revenue_cad, 0) - coalesce(s.refunds_cad, 0) - coalesce(s.units_sold, 0) * p.unit_cost)
         / nullif(coalesce(s.revenue_cad, 0) - coalesce(s.refunds_cad, 0), 0) as numeric(8, 4)) as gross_margin_pct,
    rank() over (order by coalesce(s.revenue_cad, 0) desc) as revenue_rank
from {{ ref('stg_shopify__products') }} p
left join sales s on s.product_id = p.product_id
