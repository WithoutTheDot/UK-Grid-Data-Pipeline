{{ config(materialized='table') }}

select
    hour(valid_from)                            as hour_of_day,
    dayofweek(valid_from)                       as day_of_week,
    case dayofweek(valid_from)
        when 0 then 'Sun' when 1 then 'Mon' when 2 then 'Tue'
        when 3 then 'Wed' when 4 then 'Thu' when 5 then 'Fri'
        when 6 then 'Sat'
    end                                         as day_name,
    round(avg(value_inc_vat), 2)                as avg_price_p_kwh,
    round(min(value_inc_vat), 2)                as min_price_p_kwh,
    round(max(value_inc_vat), 2)                as max_price_p_kwh,
    count(*)                                    as n_periods
from {{ ref('stg_prices') }}
where valid_from is not null
group by 1, 2, 3
order by 2, 1
