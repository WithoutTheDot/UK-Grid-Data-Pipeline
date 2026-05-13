{{ config(materialized='table') }}

with by_period as (
  select
    period_utc,
    sum(case when fuel_type in ('WIND', 'PS', 'NPSHYD')
             then generation_mw else 0 end)  as renewable_mw,
    sum(generation_mw)                       as total_mw
  from {{ ref('stg_generation') }}
  group by period_utc
),

hourly as (
  select
    date_trunc('hour', period_utc)   as hour_utc,
    avg(renewable_mw)                as renewable_mw,
    avg(total_mw)                    as total_mw
  from by_period
  group by 1
)

select
  hour_utc,
  renewable_mw,
  total_mw,
  round(renewable_mw / nullif(total_mw, 0) * 100, 2)                     as renewable_pct,
  avg(renewable_mw / nullif(total_mw, 0) * 100)
    over (order by hour_utc rows between 167 preceding and current row)   as renewable_pct_7d_avg
from hourly
order by hour_utc
