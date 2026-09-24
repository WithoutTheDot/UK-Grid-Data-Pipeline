{{ config(materialized='table') }}

-- valid_from is stored as UTC; group by UK local hour so 01:00 on the
-- chart means 01:00 on the clock, BST included
with slots as (
    select
        timezone('Europe/London', timezone('UTC', valid_from))   as local_time,
        value_inc_vat
    from {{ ref('stg_prices') }}
    where valid_from is not null
)

select
    hour(local_time)                            as hour_of_day,
    dayofweek(local_time)                       as day_of_week,
    case dayofweek(local_time)
        when 0 then 'Sun' when 1 then 'Mon' when 2 then 'Tue'
        when 3 then 'Wed' when 4 then 'Thu' when 5 then 'Fri'
        when 6 then 'Sat'
    end                                         as day_name,
    round(avg(value_inc_vat), 2)                as avg_price_p_kwh,
    round(min(value_inc_vat), 2)                as min_price_p_kwh,
    round(max(value_inc_vat), 2)                as max_price_p_kwh,
    count(*)                                    as n_periods
from slots
group by 1, 2, 3
order by 2, 1
