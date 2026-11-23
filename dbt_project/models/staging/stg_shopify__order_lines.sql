select
    id as line_id,
    order_id,
    product_id,
    title,
    upper(trim(sku)) as sku,
    quantity,
    price as unit_price,
    total_discount,
    price * quantity - total_discount as line_net
from {{ source('raw', 'shopify_order_lines') }}
