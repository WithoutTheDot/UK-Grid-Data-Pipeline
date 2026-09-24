{{ config(materialized='table') }}

select
    hour_utc,
    temp_c,
    windspeed_kmh,
    wind_direction_deg,
    cloudcover_pct,
    direct_radiation_wm2,
    precipitation_mm,
    -- Solar potential: 0-100 index. Zero at night (radiation=0).
    case when direct_radiation_wm2 is null or direct_radiation_wm2 = 0
         then 0
         else round(
             greatest(0,
                 (1 - coalesce(cloudcover_pct,100)/100.0)
                 * least(coalesce(direct_radiation_wm2,0)/800.0, 1.0)
                 * 100
             ), 1)
    end                                                             as solar_index,
    case
        when direct_radiation_wm2 is null or direct_radiation_wm2 = 0 then 'night'
        when direct_radiation_wm2 > 400 and coalesce(cloudcover_pct,100) < 30 then 'excellent'
        when direct_radiation_wm2 > 200 and coalesce(cloudcover_pct,100) < 60 then 'good'
        when direct_radiation_wm2 > 50  then 'fair'
        else 'poor'
    end                                                             as solar_condition,
    -- Wind power proxy: cube law approximation (relative, not absolute MW)
    round(power(windspeed_kmh / 20.0, 3) * 100, 1)                as wind_power_index,
    case
        when windspeed_kmh >= 50 then 'strong'
        when windspeed_kmh >= 30 then 'good'
        when windspeed_kmh >= 15 then 'moderate'
        else 'calm'
    end                                                             as wind_condition
from {{ ref('stg_weather') }}
where hour_utc is not null
order by hour_utc
