{{ config(materialized='table') }}

with scored as (
    select
        period_utc,
        value_inc_vat,
        carbon_intensity,
        intensity_index,
        renewable_pct,
        combined_score,
        -- Normalise price and carbon within all available future periods
        percent_rank() over (order by value_inc_vat asc)       as price_rank,
        percent_rank() over (order by carbon_intensity asc)    as carbon_rank
    from {{ ref('mart_price_carbon') }}
    where period_utc >= current_timestamp
      and period_utc <= current_timestamp + interval '48 hours'
      and value_inc_vat is not null
      and carbon_intensity is not null
),

ranked as (
    select
        *,
        round((price_rank + carbon_rank) / 2 * 100, 0) as window_score,
        row_number() over (order by (price_rank + carbon_rank) desc) as rank
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
        when window_score >= 80 then 'Excellent — run anything'
        when window_score >= 60 then 'Good — ideal for EV charging'
        when window_score >= 40 then 'Fair — fine for dishwasher/washing'
        else                         'Poor — delay if you can'
    end                                             as recommendation
from ranked
where rank <= 10
order by rank
