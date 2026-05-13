select
    regr_slope(total_demand_mw, temp_c) as mw_per_degree_c,
    regr_r2(total_demand_mw, temp_c)    as r_squared,
    count(*)                             as n_hours
from gold.mart_temp_vs_demand
where day_type = 'weekday'
  and temp_c is not null
  and total_demand_mw is not null
