-- Each Stripe payout should equal the day's charges net of fees, minus refunds.
select p.payout_id, p.covers_date, p.currency, p.amount, l.expected_payout
from {{ ref('stg_stripe__payouts') }} p
left join {{ ref('int_payout_ledger') }} l on l.ledger_date = p.covers_date and l.currency = p.currency
where l.expected_payout is null or abs(p.amount - l.expected_payout) > 0.01
