-- net = gross - refunds - fees on every day (allowing for rounding of the three parts)
select date_day
from {{ ref('daily_kpis') }}
where abs(net_revenue_cad - (gross_revenue_cad - refunds_cad - fees_cad)) > 0.02
