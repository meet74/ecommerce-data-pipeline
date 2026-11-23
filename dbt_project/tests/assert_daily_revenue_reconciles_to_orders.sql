-- Revenue must not drift between layers: daily_kpis against the order-level fact.
select abs(d.total - o.total) as drift
from (select sum(gross_revenue_cad) as total from {{ ref('daily_kpis') }}) d
cross join (select sum(revenue_cad) as total from {{ ref('fct_orders') }}) o
where abs(d.total - o.total) > {{ var('reconcile_tolerance_cad') }}
