{{ config(materialized='incremental', unique_key='price_key') }}

with source as (
    select * from {{ source('bronze', 'raw_prices') }}
    {% if is_incremental() %}
        where loaded_at > (select max(loaded_at) from {{ this }})
    {% endif %}
),

cleaned as (
    select
        cast(valid_from as timestamp)     as valid_from,
        cast(valid_to   as timestamp)     as valid_to,
        cast(value_inc_vat as double)     as value_inc_vat,
        product_code,
        loaded_at
    from source
    where valid_from is not null
)

select
    *,
    valid_from::varchar as price_key
from cleaned
