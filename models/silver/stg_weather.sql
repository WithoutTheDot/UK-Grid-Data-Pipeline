{{ config(materialized='incremental', unique_key='hour_utc', on_schema_change='append_new_columns') }}

with source as (
  select * from {{ source('bronze', 'raw_weather') }}
  {% if is_incremental() %}
    where loaded_at > (select max(loaded_at) from {{ this }})
  {% endif %}
),

cleaned as (
  select
    cast(time as timestamp)           as hour_utc,
    cast(temperature_2m as double)    as temp_c,
    cast(windspeed_10m as double)     as windspeed_kmh,
        nullif(cloudcover,'')::double          as cloudcover_pct,
        nullif(direct_radiation,'')::double    as direct_radiation_wm2,
        nullif(wind_direction_10m,'')::double  as wind_direction_deg,
        nullif(precipitation,'')::double       as precipitation_mm,
    loaded_at
  from source
  where time is not null
)

select * from cleaned
