{{ config(materialized='table') }}

select
  hour(loaded_at)                      as hour_of_day,
  dayofweek(loaded_at)                 as day_of_week,
  case dayofweek(loaded_at)
    when 0 then 'Sun'
    when 1 then 'Mon'
    when 2 then 'Tue'
    when 3 then 'Wed'
    when 4 then 'Thu'
    when 5 then 'Fri'
    when 6 then 'Sat'
  end                                  as day_name,
  round(avg(intensity_actual), 1)      as avg_intensity_gco2kwh,
  count(*)                             as n_readings
from {{ ref('stg_carbon') }}
where intensity_actual is not null
group by 1, 2, 3
order by 2, 1
