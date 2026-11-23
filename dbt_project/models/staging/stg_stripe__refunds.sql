select
    id as refund_id,
    charge_id,
    cast(amount / 100.0 as numeric(14, 2)) as amount,
    upper(trim(currency)) as currency,
    lower(trim(status)) as status,
    created_at,
    updated_at
from {{ source('raw', 'stripe_refunds') }}
