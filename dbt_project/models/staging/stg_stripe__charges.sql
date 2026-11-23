-- Stripe amounts are integers in the smallest currency unit.
select
    id as charge_id,
    created_at,
    updated_at,
    cast(amount / 100.0 as numeric(14, 2)) as amount,
    cast(coalesce(amount_refunded, 0) / 100.0 as numeric(14, 2)) as amount_refunded,
    upper(trim(currency)) as currency,
    lower(trim(status)) as status,
    cast(order_id as bigint) as order_id,
    cast(fee / 100.0 as numeric(14, 2)) as fee,
    cast(net / 100.0 as numeric(14, 2)) as net,
    card_brand
from {{ source('raw', 'stripe_charges') }}
