{{ config(materialized='table') }}

-- Average across the two 30-min periods within each hour so values reflect
-- instantaneous MW, not the sum of two periods.
with by_period as (
    select period_utc, fuel_type, generation_mw
    from {{ ref('stg_generation') }}
)

select
    date_trunc('hour', period_utc)   as hour_utc,
    fuel_type,
    round(avg(generation_mw), 0)     as generation_mw
from by_period
group by 1, 2
order by 1, 2
