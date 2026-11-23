select cohort_month, retention_rate
from {{ ref('monthly_cohort_retention') }}
where month_number = 0 and retention_rate <> 1
