-- CAD per unit of each currency for every calendar day. Rates are published on business
-- days only, so weekends and holidays take the most recent earlier rate (as-of join).
with rates as (
    select
        cast(rate_date as date) as rate_date,
        upper(currency) as currency,
        cast(cad_per_unit as numeric(12, 6)) as cad_per_unit
    from {{ ref('fx_rates') }}
    union all
    select cast('1900-01-01' as date), 'CAD', cast(1 as numeric(12, 6))
),

ranked as (
    select
        c.date_day,
        r.currency,
        r.cad_per_unit,
        row_number() over (partition by c.date_day, r.currency order by r.rate_date desc) as rn
    from {{ ref('int_calendar') }} c
    inner join rates r on r.rate_date <= c.date_day
)

select date_day, currency, cad_per_unit from ranked where rn = 1
