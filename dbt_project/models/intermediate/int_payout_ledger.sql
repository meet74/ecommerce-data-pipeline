-- What Stripe should have paid out per day and currency, built from charges and refunds.
with charge_net as (
    select cast(created_at as date) as ledger_date, currency, sum(net) as amount
    from {{ ref('stg_stripe__charges') }}
    where status = 'succeeded'
    group by cast(created_at as date), currency
),

refund_out as (
    select cast(created_at as date) as ledger_date, currency, -sum(amount) as amount
    from {{ ref('stg_stripe__refunds') }}
    where status = 'succeeded'
    group by cast(created_at as date), currency
),

combined as (
    select * from charge_net
    union all
    select * from refund_out
)

select ledger_date, currency, sum(amount) as expected_payout
from combined
group by ledger_date, currency
