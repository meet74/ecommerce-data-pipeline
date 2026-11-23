select
    id as payout_id,
    created_at,
    cast(created_at - interval '1 day' as date) as covers_date,
    cast(amount / 100.0 as numeric(14, 2)) as amount,
    upper(trim(currency)) as currency,
    lower(trim(status)) as status
from {{ source('raw', 'stripe_payouts') }}
