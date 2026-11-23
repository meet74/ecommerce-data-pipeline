-- One row per day, zero-filled. Definitions:
--   gross_revenue_cad  order revenue excluding tax, by order date
--   refunds_cad        refunds excluding tax, by refund date (cash view)
--   fees_cad           payment processor fees, by charge date
--   refund_rate        share of that day's orders that have been refunded (to date)
--   net_revenue_cad    gross revenue - refunds - fees
with daily_orders as (
    select
        order_date,
        count(*) as orders,
        sum(units) as units,
        sum(revenue_cad) as gross_revenue_cad,
        sum(case when customer_type = 'new' then 1 else 0 end) as new_orders,
        sum(case when customer_type = 'returning' then 1 else 0 end) as returning_orders,
        sum(case when customer_type = 'guest' then 1 else 0 end) as guest_orders,
        sum(has_refund) as refunded_orders
    from {{ ref('fct_orders') }}
    group by order_date
),

daily_refunds as (
    select refund_date, sum(refund_ex_tax_cad) as refunds_cad
    from {{ ref('int_refunds') }}
    group by refund_date
),

daily_fees as (
    select charge_date, sum(fee_cad) as fees_cad
    from {{ ref('int_charges') }}
    group by charge_date
),

joined as (
    select
        c.date_day,
        coalesce(o.orders, 0) as orders,
        coalesce(o.units, 0) as units,
        coalesce(o.gross_revenue_cad, 0) as gross_revenue_cad,
        coalesce(o.new_orders, 0) as new_orders,
        coalesce(o.returning_orders, 0) as returning_orders,
        coalesce(o.guest_orders, 0) as guest_orders,
        coalesce(o.refunded_orders, 0) as refunded_orders,
        coalesce(r.refunds_cad, 0) as refunds_cad,
        coalesce(f.fees_cad, 0) as fees_cad
    from {{ ref('int_calendar') }} c
    left join daily_orders o on o.order_date = c.date_day
    left join daily_refunds r on r.refund_date = c.date_day
    left join daily_fees f on f.charge_date = c.date_day
)

select
    date_day,
    orders,
    units,
    cast(gross_revenue_cad as numeric(16, 2)) as gross_revenue_cad,
    cast(gross_revenue_cad / nullif(orders, 0) as numeric(16, 2)) as aov_cad,
    new_orders,
    returning_orders,
    guest_orders,
    refunded_orders,
    cast(1.0 * refunded_orders / nullif(orders, 0) as numeric(8, 4)) as refund_rate,
    cast(refunds_cad as numeric(16, 2)) as refunds_cad,
    cast(fees_cad as numeric(16, 2)) as fees_cad,
    cast(gross_revenue_cad - refunds_cad - fees_cad as numeric(16, 2)) as net_revenue_cad
from joined
