-- Store orders against Stripe charges, one row per order or orphan charge.
-- issue_type, first match wins:
--   orphan_charge      a charge whose order id is not a valid order
--   pending_charge     order younger than the grace window, charge may still be coming (not an issue)
--   missing_charge     paid order with no charge
--   currency_mismatch  charge currency differs from the order currency
--   amount_mismatch    charge amount differs from the order total beyond tolerance
--   refund_mismatch    refunded amount differs between store and Stripe
--   none               everything agrees
with orders as (
    select order_id, order_number, created_at, currency, total, refund_total
    from {{ ref('int_orders') }}
    where financial_status in ('paid', 'partially_refunded', 'refunded')
),

charges as (
    select charge_id, order_id, created_at, currency, amount, refunded_amount
    from {{ ref('int_charges') }}
),

cutoff as (
    select max(created_at) - interval '{{ var("recon_grace_minutes") }} minutes' as grace_cutoff
    from {{ ref('stg_stripe__charges') }}
),

joined as (
    select
        coalesce(o.order_id, c.order_id) as order_id,
        o.order_number,
        c.charge_id,
        coalesce(o.created_at, c.created_at) as created_at,
        o.currency as order_currency,
        c.currency as charge_currency,
        o.total as order_total,
        c.amount as charge_amount,
        coalesce(o.refund_total, 0) as store_refund_total,
        coalesce(c.refunded_amount, 0) as stripe_refund_total,
        o.order_id as matched_order_id,
        (o.created_at > (select grace_cutoff from cutoff)) as is_fresh
    from orders o
    full outer join charges c on c.order_id = o.order_id
)

select
    order_id,
    order_number,
    charge_id,
    created_at,
    order_currency,
    charge_currency,
    order_total,
    charge_amount,
    charge_amount - order_total as amount_diff,
    store_refund_total,
    stripe_refund_total,
    case
        when matched_order_id is null then 'orphan_charge'
        when charge_id is null and is_fresh then 'pending_charge'
        when charge_id is null then 'missing_charge'
        when charge_currency <> order_currency then 'currency_mismatch'
        when abs(charge_amount - order_total) > {{ var('recon_amount_tolerance') }} then 'amount_mismatch'
        when abs(store_refund_total - stripe_refund_total) > {{ var('recon_amount_tolerance') }} then 'refund_mismatch'
        else 'none'
    end as issue_type
from joined
