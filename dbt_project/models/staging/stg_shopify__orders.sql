-- One row per source order id. Flags are kept rather than rows dropped so the
-- cleaning is visible and countable; downstream models filter on them.
with src as (
    select * from {{ source('raw', 'shopify_orders') }}
),

cleaned as (
    select
        id as order_id,
        order_number,
        created_at,
        updated_at,
        customer_id,
        nullif(lower(trim(email)), '') as email_norm,
        upper(trim(currency)) as currency,
        lower(trim(financial_status)) as financial_status,
        nullif(lower(trim(fulfillment_status)), '') as fulfillment_status,
        cancelled_at,
        coalesce(test, false) as is_test,
        lower(trim(source_name)) as source_name,
        subtotal_price,
        total_discounts,
        total_shipping_price,
        total_tax,
        total_price,
        nullif(upper(trim(discount_code)), '') as discount_code,
        nullif(upper(trim(shipping_country)), '') as shipping_country
    from src
),

ranked as (
    -- the source occasionally emits the same order twice (double submit); the first one wins
    select
        *,
        row_number() over (partition by order_number order by created_at, order_id) as order_number_rank
    from cleaned
)

select
    order_id, order_number, created_at, updated_at, customer_id, email_norm, currency, financial_status,
    fulfillment_status, cancelled_at, is_test, source_name, subtotal_price, total_discounts,
    total_shipping_price, total_tax, total_price, discount_code, shipping_country,
    (order_number_rank > 1) as is_duplicate,
    (cancelled_at is not null or financial_status = 'voided') as is_cancelled
from ranked
