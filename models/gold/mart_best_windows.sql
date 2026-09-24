{{ config(materialized='table') }}

with scored as (
    select
        period_utc,
        value_inc_vat,
        carbon_intensity,
        intensity_index,
        renewable_pct,
        percent_rank() over (order by value_inc_vat asc)       as price_rank,
        percent_rank() over (order by carbon_intensity asc)    as carbon_rank
    from {{ ref('mart_price_carbon') }}
    -- include the half-hour we're currently in, it started before now
    where period_utc > current_timestamp - interval '30 minutes'
      and period_utc <= current_timestamp + interval '48 hours'
      and value_inc_vat is not null
      and carbon_intensity is not null
),

-- percent_rank is 0 for the cheapest/cleanest slot, so flip it:
-- 100 = cheapest and cleanest, 0 = most expensive and dirtiest
ranked as (
    select
        *,
        round((1 - (price_rank + carbon_rank) / 2) * 100, 0) as window_score,
        row_number() over (order by (price_rank + carbon_rank) asc, period_utc) as rank
    from scored
)

select
    rank,
    period_utc,
    period_utc + interval '30 minutes'              as period_to,
    round(value_inc_vat, 2)                         as price_p_kwh,
    round(carbon_intensity, 0)                      as carbon_gco2_kwh,
    intensity_index,
    round(renewable_pct, 1)                         as renewable_pct,
    round(window_score, 0)                          as window_score,
    case
        -- same bands as the colours on the page and recommendation() in app.py
        when window_score >= 75 then 'Excellent, run anything'
        when window_score >= 55 then 'Good, go for it'
        when window_score >= 35 then 'Fair, non-urgent can wait'
        else                         'Poor, consider waiting'
    end                                             as recommendation
from ranked
order by rank
