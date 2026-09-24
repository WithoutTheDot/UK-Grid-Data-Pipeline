{{ config(materialized='incremental', unique_key='carbon_key') }}

with source as (
  select * from {{ source('bronze', 'raw_carbon') }}
  {% if is_incremental() %}
    where loaded_at > (select max(loaded_at) from {{ this }})
  {% endif %}
),

joined as (
  select
    cast(s.regionid as integer)         as regionid,
    s.shortname,
    r.full_name,
    cast(s.intensity_actual as double)  as intensity_actual,
    s.generationmix,
    s.loaded_at
  from source s
  left join {{ ref('region_lookup') }} r
    on cast(s.regionid as integer) = r.regionid
  where s.regionid is not null
)

select
  *,
  regionid::varchar || '_' || loaded_at::varchar as carbon_key
from joined
