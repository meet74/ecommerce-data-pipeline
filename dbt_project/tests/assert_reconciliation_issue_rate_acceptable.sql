-- Fails the run if more than max_issue_rate of reconciled rows have a problem.
select issues, total
from (
    select
        sum(case when issue_type not in ('none', 'pending_charge') then 1 else 0 end) as issues,
        count(*) as total
    from {{ ref('fct_payment_reconciliation') }}
) t
where 1.0 * issues / nullif(total, 0) > {{ var('max_issue_rate') }}
