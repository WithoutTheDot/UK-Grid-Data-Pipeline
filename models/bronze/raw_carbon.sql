select * from {{ source('bronze', 'raw_carbon') }}
