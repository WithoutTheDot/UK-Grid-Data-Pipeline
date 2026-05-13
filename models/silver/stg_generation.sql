{{ config(materialized='incremental', unique_key='settlement_key') }}

with source as (
  select * from {{ source('bronze', 'raw_generation') }}
  {% if is_incremental() %}
    where loaded_at > (select max(loaded_at) from {{ this }})
  {% endif %}
),

cleaned as (
  select
    cast(settlement_date as date)                                        as settlement_date,
    cast(settlement_period as integer)                                   as settlement_period,
    cast(settlement_date as timestamp)
      + ((settlement_period - 1) * interval '30 minutes')               as period_utc,
    upper(trim(fuel_type))                                               as fuel_type,
    cast(generation as double)                                           as generation_mw,
    loaded_at
  from source
  where generation is not null
    and cast(settlement_period as integer) between 1 and 48
)

select
  *,
  settlement_date::varchar || '_' || settlement_period::varchar as settlement_key
from cleaned
