{{ config(materialized='table') }}

with by_period as (
    select
        period_utc,
        sum(generation_mw)                                           as total_mw,
        sum(case when fuel_type in ('WIND','PS','NPSHYD')
                 then generation_mw else 0 end)                      as renewable_mw
    from {{ ref('stg_generation') }}
    group by period_utc
),

gen_hourly as (
    select
        date_trunc('hour', period_utc)   as hour_utc,
        avg(total_mw)                    as total_mw,
        avg(renewable_mw)                as renewable_mw
    from by_period
    group by 1
),

joined as (
    select
        g.hour_utc,
        g.total_mw,
        g.renewable_mw,
        round(g.renewable_mw / nullif(g.total_mw, 0) * 100, 1)                     as renewable_pct,
        w.temp_c,
        w.windspeed_kmh,
        hour(g.hour_utc)                                                            as hour_of_day,
        case when dayofweek(g.hour_utc) in (0,6) then 'weekend' else 'weekday' end as day_type,
        case when
            w.temp_c < 7
            and w.windspeed_kmh < 20
            and hour(g.hour_utc) between 16 and 20
            and (g.renewable_mw / nullif(g.total_mw, 0)) < 0.30
        then true else false end                                                    as is_stress_hour
    from gen_hourly g
    left join {{ ref('stg_weather') }} w on g.hour_utc = w.hour_utc
    where w.temp_c is not null
)

select
    *,
    case
        when temp_c < 4                                then 'freezing'
        when temp_c < 10                               then 'cold'
        when temp_c < 16                               then 'mild'
        else                                                'warm'
    end                                                     as temp_band
from joined
order by hour_utc
