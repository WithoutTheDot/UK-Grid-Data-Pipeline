{{ config(materialized='table') }}

with prices as (
    select
        valid_from                                      as period_utc,
        valid_to,
        value_inc_vat
    from {{ ref('stg_prices') }}
),

carbon as (
    select
        period_from                                     as period_utc,
        intensity_best,
        intensity_index
    from {{ ref('stg_carbon_national') }}
),

gen as (
    select
        period_utc,
        sum(generation_mw)                              as total_mw,
        sum(case when fuel_type in ('WIND','PS','NPSHYD')
                 then generation_mw else 0 end)         as renewable_mw
    from {{ ref('stg_generation') }}
    group by 1
)

select
    coalesce(p.period_utc, c.period_utc)                as period_utc,
    p.value_inc_vat,
    c.intensity_best                                    as carbon_intensity,
    c.intensity_index,
    g.total_mw,
    round(g.renewable_mw / nullif(g.total_mw,0)*100,1) as renewable_pct,
    hour(coalesce(p.period_utc, c.period_utc))          as hour_of_day,
    dayofweek(coalesce(p.period_utc, c.period_utc))     as day_of_week
from prices p
full outer join carbon c
    on p.period_utc = c.period_utc
left join gen g
    on p.period_utc = g.period_utc
order by coalesce(p.period_utc, c.period_utc)
