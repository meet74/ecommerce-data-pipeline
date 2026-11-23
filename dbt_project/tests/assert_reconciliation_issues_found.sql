{{ config(severity='warn') }}
-- Warns (does not fail) whenever store and payments disagree, so the issues surface in every run.
select issue_type, count(*) as n
from {{ ref('fct_payment_reconciliation') }}
where issue_type not in ('none', 'pending_charge')
group by issue_type
