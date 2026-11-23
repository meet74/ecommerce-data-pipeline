with cleaned as (
    select
        id as customer_id,
        nullif(lower(trim(email)), '') as email_norm,
        nullif(trim(first_name), '') as first_name_raw,
        nullif(trim(last_name), '') as last_name_raw,
        case
            when upper(trim(country)) in ('CA', 'CANADA') then 'CA'
            when upper(trim(country)) in ('US', 'USA', 'UNITED STATES') then 'US'
            else nullif(upper(trim(country)), '')
        end as country,
        lower(trim(state)) as account_state,
        coalesce(accepts_marketing, false) as accepts_marketing,
        created_at,
        updated_at
    from {{ source('raw', 'shopify_customers') }}
),

keyed as (
    select
        *,
        coalesce(email_norm, 'id:' || cast(customer_id as varchar)) as customer_key
    from cleaned
)

select
    customer_id,
    customer_key,
    email_norm,
    upper(substr(first_name_raw, 1, 1)) || lower(substr(first_name_raw, 2)) as first_name,
    last_name_raw as last_name,
    country,
    account_state,
    accepts_marketing,
    created_at,
    updated_at,
    -- same person registered twice under different casing/whitespace: keep the oldest id
    min(customer_id) over (partition by customer_key) as canonical_customer_id,
    customer_id <> min(customer_id) over (partition by customer_key) as is_duplicate
from keyed
