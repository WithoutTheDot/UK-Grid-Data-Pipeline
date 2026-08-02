{{ config(materialized='incremental', unique_key='hour_utc', on_schema_change='append_new_columns') }}

with source as (
  select * from {{ source('bronze', 'raw_weather') }}
  {% if is_incremental() %}
    where loaded_at > (select max(loaded_at) from {{ this }})
  {% endif %}
),

cleaned as (
  select
    cast(time as timestamp)                                as hour_utc,
    nullif(nullif(temperature_2m, ''), 'None')::double    as temp_c,
    nullif(nullif(windspeed_10m, ''), 'None')::double     as windspeed_kmh,
    nullif(nullif(cloudcover, ''), 'None')::double        as cloudcover_pct,
    nullif(nullif(direct_radiation, ''), 'None')::double  as direct_radiation_wm2,
    nullif(nullif(wind_direction_10m, ''), 'None')::double as wind_direction_deg,
    nullif(nullif(precipitation, ''), 'None')::double     as precipitation_mm,
    loaded_at
  from source
  where time is not null
)

select * from cleaned
