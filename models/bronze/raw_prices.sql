select * from {{ source('bronze', 'raw_prices') }}
