{{ config(materialized='table') }}

with latest as (
    select
        regionid,
        shortname,
        full_name,
        intensity_actual,
        generationmix,
        loaded_at,
        row_number() over (partition by regionid order by loaded_at desc) as rn
    from {{ ref('stg_carbon') }}
    where intensity_actual is not null
)

select
    regionid,
    shortname,
    full_name,
    intensity_actual,
    generationmix,
    loaded_at                               as snapshot_at,
    case
        when intensity_actual < 50  then 'very low'
        when intensity_actual < 100 then 'low'
        when intensity_actual < 200 then 'moderate'
        when intensity_actual < 300 then 'high'
        else                             'very high'
    end                                     as intensity_band
from latest
where rn = 1
order by intensity_actual asc
