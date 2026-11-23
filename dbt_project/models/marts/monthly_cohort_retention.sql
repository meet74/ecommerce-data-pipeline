-- Customers grouped by the month of their first order. retention_rate is the share of the
-- cohort that ordered again in month N (month 0 is always 100%). Guest orders without an
-- identity are left out.
with orders as (
    select
        customer_key,
        cast(date_trunc('month', created_at) as date) as order_month,
        order_seq
    from {{ ref('fct_orders') }}
    where customer_key is not null
),

cohorts as (
    select customer_key, order_month as cohort_month
    from orders
    where order_seq = 1
),

cohort_size as (
    select cohort_month, count(*) as cohort_size
    from cohorts
    group by cohort_month
),

activity as (
    select c.cohort_month, o.order_month, count(distinct o.customer_key) as active_customers
    from orders o
    inner join cohorts c on c.customer_key = o.customer_key
    group by c.cohort_month, o.order_month
),

months as (
    select distinct order_month from orders
),

grid as (
    select s.cohort_month, s.cohort_size, m.order_month
    from cohort_size s
    inner join months m on m.order_month >= s.cohort_month
)

select
    g.cohort_month,
    g.order_month,
    cast((extract(year from g.order_month) - extract(year from g.cohort_month)) * 12
         + (extract(month from g.order_month) - extract(month from g.cohort_month)) as integer) as month_number,
    g.cohort_size,
    coalesce(a.active_customers, 0) as active_customers,
    cast(1.0 * coalesce(a.active_customers, 0) / g.cohort_size as numeric(8, 4)) as retention_rate
from grid g
left join activity a on a.cohort_month = g.cohort_month and a.order_month = g.order_month
