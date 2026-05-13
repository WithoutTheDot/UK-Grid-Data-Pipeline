select * from {{ source('bronze', 'raw_generation') }}
