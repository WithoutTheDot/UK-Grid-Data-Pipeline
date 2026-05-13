import os
from pathlib import Path
from collections import defaultdict

import duckdb
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

DB_PATH = os.environ.get(
    'ENERGY_DB_PATH',
    str(Path(__file__).parent.parent / 'energy.duckdb')
)

TEMPLATES = Path(__file__).parent / "templates"


def query(sql: str, params=None) -> list[dict]:
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        rel = con.execute(sql, params or [])
        cols = [d[0] for d in rel.description]
        return [dict(zip(cols, row)) for row in rel.fetchall()]
    finally:
        con.close()


app = FastAPI(title="UK Energy Grid")
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


# ── Main page ────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    return (TEMPLATES / "index.html").read_text()


# ── KPI ──────────────────────────────────────────────────────────
@app.get("/api/kpi")
async def kpi():
    renewable = query("""
        select hour_utc::varchar as cleanest_hour,
               round(renewable_pct,1) as renewable_pct,
               round(renewable_pct_7d_avg,1) as avg_7d
        from main_gold.mart_renewable_mix
        where date_trunc('day', hour_utc) = current_date
        order by renewable_pct desc limit 1
    """) or query("""
        select hour_utc::varchar as cleanest_hour,
               round(renewable_pct,1) as renewable_pct,
               round(renewable_pct_7d_avg,1) as avg_7d
        from main_gold.mart_renewable_mix order by hour_utc desc limit 1
    """)
    demand = query("""
        select round(avg(total_demand_mw)/1000,1) as avg_demand_gw,
               round(max(total_demand_mw)/1000,1) as peak_demand_gw
        from main_gold.mart_temp_vs_demand
        where date_trunc('day', hour_utc) = current_date
    """)
    carbon = query("""
        select round(avg(intensity_actual),0) as avg_carbon
        from main_gold.mart_regional_carbon
    """)
    stress = query("""
        select count(*) as stress_hours from main_gold.mart_grid_stress
        where is_stress_hour = true
        and date_trunc('day', hour_utc) >= current_date - interval '7 days'
    """)
    current_price = query("""
        select round(value_inc_vat,2) as current_price_p_kwh
        from main_gold.mart_price_carbon
        where period_utc <= current_timestamp
        order by period_utc desc limit 1
    """)
    result = (renewable[0] if renewable else {})
    result.update(demand[0] if demand else {})
    result.update(carbon[0] if carbon else {})
    result.update(stress[0] if stress else {})
    result.update(current_price[0] if current_price else {})
    return JSONResponse(result)


# ── Now signal ───────────────────────────────────────────────────
@app.get("/api/now")
async def now():
    rows = query("""
        with current_period as (
            select
                p.period_utc,
                round(avg(p.value_inc_vat), 2)    as price_p_kwh,
                round(avg(p.carbon_intensity), 0) as carbon_gco2_kwh,
                max(p.intensity_index)             as intensity_index,
                round(coalesce(avg(p.renewable_pct), r.renewable_pct), 1) as renewable_pct
            from main_gold.mart_price_carbon p
            left join (
                select renewable_pct
                from main_gold.mart_renewable_mix
                order by hour_utc desc limit 1
            ) r on true
            where p.period_utc <= current_timestamp
            group by p.period_utc, r.renewable_pct
            order by p.period_utc desc limit 1
        ),
        scored as (
            select cp.*,
                   bw.window_score,
                   bw.recommendation,
                   bw.rank
            from current_period cp
            left join main_gold.mart_best_windows bw on bw.period_utc = cp.period_utc
        ),
        next_window as (
            select period_utc::varchar  as next_period_utc,
                   price_p_kwh          as next_price,
                   carbon_gco2_kwh      as next_carbon,
                   window_score         as next_score,
                   recommendation       as next_recommendation
            from main_gold.mart_best_windows
            where period_utc > current_timestamp
            order by period_utc asc limit 1
        )
        select s.period_utc::varchar as period_utc,
               s.price_p_kwh, s.carbon_gco2_kwh, s.intensity_index,
               s.renewable_pct, s.window_score, s.recommendation, s.rank,
               n.next_period_utc, n.next_price, n.next_carbon,
               n.next_score, n.next_recommendation
        from scored s left join next_window n on true
    """)
    return JSONResponse(rows[0] if rows else {})


# ── Appliance window finder ──────────────────────────────────────
@app.get("/api/appliance-windows")
async def appliance_windows(hours: float = 2.0):
    n = max(1, round(hours * 2))
    rows = query("""
        select period_utc::varchar            as period_utc,
               round(avg(value_inc_vat), 2)    as price_p_kwh,
               round(avg(carbon_intensity), 0) as carbon_gco2_kwh,
               round(avg(renewable_pct), 1)    as renewable_pct
        from main_gold.mart_price_carbon
        where period_utc >= current_timestamp
          and period_utc < current_timestamp + interval '36 hours'
          and value_inc_vat is not null
        group by period_utc
        order by period_utc asc
    """)
    if len(rows) < n:
        return JSONResponse([])

    windows = []
    for i in range(len(rows) - n + 1):
        block = rows[i:i + n]
        prices  = [r['price_p_kwh']    for r in block if r['price_p_kwh']    is not None]
        carbons = [r['carbon_gco2_kwh'] for r in block if r['carbon_gco2_kwh'] is not None]
        renews  = [r['renewable_pct']   for r in block if r['renewable_pct']  is not None]
        if len(prices) < n * 0.8:
            continue
        windows.append({
            'start':         block[0]['period_utc'],
            'end':           block[-1]['period_utc'],
            'avg_price':     round(sum(prices) / len(prices), 2),
            'avg_carbon':    int(sum(carbons) / len(carbons)) if carbons else None,
            'avg_renewable': round(sum(renews) / len(renews), 1) if renews else None,
        })

    if not windows:
        return JSONResponse([])

    all_p = [w['avg_price']  for w in windows]
    all_c = [w['avg_carbon'] for w in windows if w['avg_carbon'] is not None]
    min_p, max_p = min(all_p), max(all_p)
    min_c, max_c = (min(all_c), max(all_c)) if all_c else (0, 1)
    p_range = max_p - min_p or 1
    c_range = max_c - min_c or 1

    for w in windows:
        ps = (w['avg_price'] - min_p) / p_range
        cs = ((w['avg_carbon'] or min_c) - min_c) / c_range
        w['score'] = round((1 - (ps * 0.5 + cs * 0.5)) * 100)

    windows.sort(key=lambda w: -w['score'])
    return JSONResponse(windows[:5])


# ── Windows by day (today + tomorrow) ────────────────────────────
@app.get("/api/windows-by-day")
async def windows_by_day():
    rows = query("""
        select period_utc::varchar            as period_utc,
               round(avg(value_inc_vat), 2)    as price_p_kwh,
               round(avg(carbon_intensity), 0) as carbon_gco2_kwh,
               round(avg(renewable_pct), 1)    as renewable_pct,
               max(intensity_index)             as intensity_index
        from main_gold.mart_price_carbon
        where period_utc >= current_timestamp
          and period_utc < current_date + interval '2 days'
          and value_inc_vat is not null
        group by period_utc
        order by period_utc asc
    """)
    if not rows:
        return JSONResponse({})

    all_p = [r['price_p_kwh']    for r in rows if r['price_p_kwh']    is not None]
    all_c = [r['carbon_gco2_kwh'] for r in rows if r['carbon_gco2_kwh'] is not None]
    min_p, max_p = (min(all_p), max(all_p)) if all_p else (0, 1)
    min_c, max_c = (min(all_c), max(all_c)) if all_c else (0, 1)
    p_range = max_p - min_p or 1
    c_range = max_c - min_c or 1

    def score_row(r):
        if r['price_p_kwh'] is None or r['carbon_gco2_kwh'] is None:
            return 0
        ps = (r['price_p_kwh']    - min_p) / p_range
        cs = (r['carbon_gco2_kwh'] - min_c) / c_range
        return round((1 - (ps * 0.5 + cs * 0.5)) * 100)

    def rec(s):
        if s >= 75: return 'Excellent — run anything'
        if s >= 55: return 'Good — go for it'
        if s >= 35: return 'Fair — non-urgent can wait'
        return 'Poor — consider waiting'

    by_day: dict = {}
    for r in rows:
        dk = r['period_utc'][:10]
        r['score'] = score_row(r)
        r['recommendation'] = rec(r['score'])
        by_day.setdefault(dk, []).append(r)

    result = {dk: sorted(v, key=lambda x: -x['score'])[:5] for dk, v in by_day.items()}
    return JSONResponse(result)


# ── Best windows ─────────────────────────────────────────────────
@app.get("/api/best-windows")
async def best_windows():
    rows = query("""
        select rank,
               period_utc::varchar    as period_utc,
               period_to::varchar     as period_to,
               price_p_kwh,
               carbon_gco2_kwh,
               intensity_index,
               renewable_pct,
               window_score,
               recommendation
        from main_gold.mart_best_windows
        order by rank limit 5
    """)
    return JSONResponse(rows)


# ── Price + carbon combined ───────────────────────────────────────
@app.get("/api/prices-carbon")
async def prices_carbon():
    rows = query("""
        select period_utc::varchar as period_utc,
               round(value_inc_vat,2)    as price_p_kwh,
               round(carbon_intensity,0) as carbon_intensity,
               intensity_index,
               round(renewable_pct,1)    as renewable_pct
        from main_gold.mart_price_carbon
        order by period_utc desc limit 200
    """)
    return JSONResponse(list(reversed(rows)))


# ── Combined best-time heatmap ────────────────────────────────────
@app.get("/api/combined-heatmap")
async def combined_heatmap():
    rows = query("""
        select p.hour_of_day, p.day_of_week, p.day_name,
               p.avg_price_p_kwh, c.avg_intensity_gco2kwh as avg_carbon
        from main_gold.mart_price_heatmap p
        join main_gold.mart_carbon_heatmap c
          on p.hour_of_day = c.hour_of_day and p.day_of_week = c.day_of_week
        order by p.day_of_week, p.hour_of_day
    """)
    if not rows:
        return JSONResponse([])
    prices  = [r['avg_price_p_kwh'] for r in rows]
    carbons = [r['avg_carbon']       for r in rows]
    min_p, max_p = min(prices),  max(prices)
    min_c, max_c = min(carbons), max(carbons)
    p_range = max_p - min_p or 1
    c_range = max_c - min_c or 1
    for r in rows:
        ps = (r['avg_price_p_kwh'] - min_p) / p_range
        cs = (r['avg_carbon']      - min_c) / c_range
        r['score'] = round((1 - (ps * 0.5 + cs * 0.5)) * 100)
    return JSONResponse(rows)


# ── Solar + weather extended ──────────────────────────────────────
@app.get("/api/solar-weather")
async def solar_weather():
    rows = query("""
        select hour_utc::varchar as hour_utc,
               temp_c, windspeed_kmh, wind_direction_deg,
               cloudcover_pct, direct_radiation_wm2, precipitation_mm,
               solar_index, solar_condition,
               wind_power_index, wind_condition
        from main_gold.mart_solar_weather
        order by hour_utc desc limit 96
    """)
    return JSONResponse(list(reversed(rows)))


# ── Interconnectors ───────────────────────────────────────────────
@app.get("/api/interconnectors")
async def interconnectors():
    interconn = ('INTELEC','INTFR','INTEW','INTIRL','INTGRNL','INTIFA2','INTNED','INTNEM','INTVKL')
    in_clause = ','.join(f"'{f}'" for f in interconn)
    rows = query(f"""
        select hour_utc::varchar as hour_utc, fuel_type,
               round(generation_mw, 0) as generation_mw
        from main_gold.mart_fuel_mix
        where fuel_type in ({in_clause})
        order by hour_utc desc limit 48 * 10
    """)
    rows = list(reversed(rows))
    labels_seen, labels_set = [], set()
    by_link: dict = defaultdict(dict)
    for r in rows:
        h = r['hour_utc'][:13]
        if h not in labels_set:
            labels_seen.append(h)
            labels_set.add(h)
        by_link[r['fuel_type']][h] = r['generation_mw']
    links = {ft: [by_link[ft].get(h) for h in labels_seen] for ft in by_link}
    return JSONResponse({"labels": labels_seen, "links": links})


@app.get("/api/fuel-mix")
async def fuel_mix():
    rows = query("""
        select hour_utc::varchar as hour_utc, fuel_type,
               round(generation_mw,0) as generation_mw
        from main_gold.mart_fuel_mix
        order by hour_utc desc limit 48*20
    """)
    rows = list(reversed(rows))
    labels_seen, labels_set = [], set()
    fuel_data: dict = defaultdict(dict)
    for r in rows:
        h = r['hour_utc'][:13]
        if h not in labels_set:
            labels_seen.append(h)
            labels_set.add(h)
        fuel_data[r['fuel_type']][h] = r['generation_mw']
    fuels = {ft: [fuel_data[ft].get(h, 0) for h in labels_seen] for ft in fuel_data}
    return JSONResponse({"labels": labels_seen, "fuels": fuels})


@app.get("/api/temp-vs-demand")
async def temp_vs_demand():
    rows = query("""
        select hour_utc::varchar as hour_utc, total_demand_mw, temp_c, day_type
        from main_gold.mart_temp_vs_demand
        where temp_c is not null and total_demand_mw is not null
        order by hour_utc desc limit 2000
    """)
    return JSONResponse(rows)


@app.get("/api/renewable-mix")
async def renewable_mix():
    rows = query("""
        select
            r.hour_utc::varchar   as hour_utc,
            r.renewable_pct,
            r.renewable_pct_7d_avg,
            w.temp_c,
            w.windspeed_kmh
        from main_gold.mart_renewable_mix r
        left join main_gold.mart_solar_weather w on r.hour_utc = w.hour_utc
        order by r.hour_utc desc limit 720
    """)
    return JSONResponse(list(reversed(rows)))


@app.get("/api/carbon-heatmap")
async def carbon_heatmap():
    rows = query("""
        select hour_of_day, day_of_week, day_name, avg_intensity_gco2kwh
        from main_gold.mart_carbon_heatmap order by day_of_week, hour_of_day
    """)
    return JSONResponse(rows)


@app.get("/api/regional-carbon")
async def regional_carbon():
    rows = query("""
        select shortname, full_name, intensity_actual, intensity_band
        from main_gold.mart_regional_carbon order by intensity_actual asc
    """)
    return JSONResponse(rows)


@app.get("/api/grid-stress")
async def grid_stress():
    rows = query("""
        select hour_utc::varchar as hour_utc, total_mw, renewable_pct,
               temp_c, windspeed_kmh, is_stress_hour, temp_band, day_type
        from main_gold.mart_grid_stress order by hour_utc desc limit 168
    """)
    return JSONResponse(list(reversed(rows)))


@app.get("/api/demand-profile")
async def demand_profile():
    rows = query("""
        select hour_of_day, day_type,
               round(avg(total_demand_mw)/1000,2) as avg_gw,
               round(min(total_demand_mw)/1000,2) as min_gw,
               round(max(total_demand_mw)/1000,2) as max_gw
        from main_gold.mart_temp_vs_demand
        where total_demand_mw is not null
        group by 1, 2 having count(*) >= 2
        order by 1, 2
    """)
    return JSONResponse(rows)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
