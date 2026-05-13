{{ config(materialized='incremental', unique_key='period_key') }}

with source as (
    select * from {{ source('bronze', 'raw_carbon_national') }}
    {% if is_incremental() %}
        where loaded_at > (select max(loaded_at) from {{ this }})
    {% endif %}
),

cleaned as (
    select
        strptime(replace(from_time,'Z','+00:00'), '%Y-%m-%dT%H:%M%z')  as period_from,
        strptime(replace(to_time,  'Z','+00:00'), '%Y-%m-%dT%H:%M%z')  as period_to,
        nullif(intensity_actual,  '')::double                        as intensity_actual,
        nullif(intensity_forecast,'')::double                        as intensity_forecast,
        coalesce(
            nullif(intensity_actual,''),
            nullif(intensity_forecast,'')
        )::double                                                     as intensity_best,
        intensity_index,
        loaded_at
    from source
    where from_time is not null
)

select
    *,
    period_from::varchar as period_key
from cleaned
