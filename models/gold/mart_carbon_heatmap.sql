{{ config(materialized='table') }}

-- Average carbon intensity for each half-hour slot, grouped by UK local
-- hour and weekday. Uses the national per-slot figures (actual where
-- published, forecast otherwise) so every fetch fills a whole range of
-- cells, not just the hour the pipeline happened to run in.
with slots as (
  select
    timezone('Europe/London', period_from)   as local_time,
    intensity_best
  from {{ ref('stg_carbon_national') }}
  where intensity_best is not null
)

select
  hour(local_time)                     as hour_of_day,
  dayofweek(local_time)                as day_of_week,
  case dayofweek(local_time)
    when 0 then 'Sun'
    when 1 then 'Mon'
    when 2 then 'Tue'
    when 3 then 'Wed'
    when 4 then 'Thu'
    when 5 then 'Fri'
    when 6 then 'Sat'
  end                                  as day_name,
  round(avg(intensity_best), 1)        as avg_intensity_gco2kwh,
  count(*)                             as n_readings
from slots
group by 1, 2, 3
order by 2, 1
