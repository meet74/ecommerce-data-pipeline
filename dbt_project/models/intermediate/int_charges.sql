-- Succeeded charges with Stripe refunds attached and amounts in CAD at the charge date.
with refunds as (
    select charge_id, sum(amount) as refunded_amount
    from {{ ref('stg_stripe__refunds') }}
    where status = 'succeeded'
    group by charge_id
)

select
    ch.charge_id,
    ch.order_id,
    ch.created_at,
    cast(ch.created_at as date) as charge_date,
    ch.currency,
    ch.amount,
    ch.fee,
    ch.net,
    coalesce(r.refunded_amount, 0) as refunded_amount,
    fx.cad_per_unit as fx_rate_cad,
    ch.amount * fx.cad_per_unit as amount_cad,
    ch.fee * fx.cad_per_unit as fee_cad
from {{ ref('stg_stripe__charges') }} ch
left join refunds r on r.charge_id = ch.charge_id
left join {{ ref('int_fx_daily') }} fx on fx.date_day = cast(ch.created_at as date) and fx.currency = ch.currency
where ch.status = 'succeeded'
