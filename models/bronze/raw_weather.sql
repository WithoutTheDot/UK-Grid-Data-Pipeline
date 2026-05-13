select * from {{ source('bronze', 'raw_weather') }}
