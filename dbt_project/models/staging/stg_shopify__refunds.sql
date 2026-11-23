select
    id as refund_id,
    order_id,
    upper(trim(currency)) as currency,
    amount,
    trim(note) as reason,
    created_at,
    updated_at
from {{ source('raw', 'shopify_refunds') }}
