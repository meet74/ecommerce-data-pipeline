select
    id as product_id,
    trim(title) as title,
    upper(substr(trim(product_type), 1, 1)) || lower(substr(trim(product_type), 2)) as product_type,
    coalesce(nullif(trim(vendor), ''), 'Unknown') as vendor,
    lower(trim(status)) as status,
    upper(trim(sku)) as sku,
    price as list_price,
    cost as unit_cost,
    created_at,
    updated_at
from {{ source('raw', 'shopify_products') }}
