{{ config(materialized='table') }}

with gen as (
  select
    date_trunc('hour', period_utc)          as hour_utc,
    avg(period_total_mw)                    as total_demand_mw
  from (
    select period_utc, sum(generation_mw)   as period_total_mw
    from {{ ref('stg_generation') }}
    group by period_utc
  )
  group by 1
),

weather as (
  select hour_utc, temp_c, windspeed_kmh
  from {{ ref('stg_weather') }}
)

select
  g.hour_utc,
  g.total_demand_mw,
  w.temp_c,
  w.windspeed_kmh,
  dayofweek(g.hour_utc)                                        as day_of_week,
  hour(g.hour_utc)                                             as hour_of_day,
  case when dayofweek(g.hour_utc) in (0, 6)
       then 'weekend' else 'weekday' end                       as day_type
from gen g
left join weather w on g.hour_utc = w.hour_utc
