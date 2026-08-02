# UK Energy Grid — Project Handoff

Consumer-facing smart energy dashboard for UK EV owners and smart home users.
Shows live grid data (price, carbon, generation mix) and helps users find the
cheapest, cleanest times to run appliances.

---

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI (Python 3.12), served via uvicorn |
| Database | DuckDB (single file: `energy.duckdb`) |
| Data pipeline | dbt-core + dbt-duckdb |
| Frontend | Vanilla JS + Chart.js 4.4, server-rendered HTML |

No Node.js. No React. No auth.

---

## How to run

```bash
# install deps (once)
pip install -r requirements.txt --break-system-packages

# run the app
python3 dashboard/app.py
# → http://localhost:8000

# or with auto-reload
python3 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000 --reload

# run the ingest + dbt pipeline manually
bash run_pipeline.sh
```

### Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENERGY_DB_PATH` | `./energy.duckdb` | Path to DuckDB file |

---

## Project structure

```
UKEngergy/
├── dashboard/
│   ├── app.py                  ← FastAPI app — ALL backend logic lives here
│   ├── static/                 ← Static assets
│   └── templates/
│       ├── index.html          ← Single-page app (~1420 lines, 3 tabs, vanilla JS)
│       ├── login.html          ← Orphaned — no auth routes exist in app.py
│       └── signup.html         ← Orphaned — no auth routes exist in app.py
├── ingest/
│   └── fetch_all.py            ← Pulls from 5 sources (4 APIs), writes to bronze tables
├── models/
│   ├── bronze/                 ← dbt views over raw tables (no transform)
│   ├── silver/                 ← dbt incremental models: type-cast, dedupe
│   └── gold/                   ← dbt tables: joined, aggregated, query-ready
├── seeds/
│   └── region_lookup.csv       ← Maps Carbon Intensity regionid → full name
├── tests/
│   └── test_api.py             ← pytest suite (monkeypatches query(), no live DB)
├── energy.duckdb               ← Single database file (all schemas)
├── run_pipeline.sh             ← Runs fetch_all.py + dbt; called by cron
├── requirements.txt
├── dbt_project.yml
└── profiles.yml                ← dbt profile (reads ENERGY_DB_PATH)
```

---

## Data pipeline

### Ingest (`ingest/fetch_all.py`)

Runs every 30 minutes (cron or manual). Entry point: `main()` — safe to import
without side effects. Pulls from five sources:

| Source | Data | Table |
|--------|------|-------|
| Elexon BMRS | Half-hourly generation by fuel type | `bronze.raw_generation` |
| Open-Meteo | Hourly weather (Birmingham, 52.48°N 1.90°W) | `bronze.raw_weather` |
| Carbon Intensity API | National carbon intensity + forecast (48h) | `bronze.raw_carbon_national` |
| Carbon Intensity API | Regional carbon intensity (14 regions) | `bronze.raw_carbon` |
| Octopus Energy API | Agile half-hourly prices (48h forward) | `bronze.raw_prices` |

The pipeline script: `run_pipeline.sh`
```bash
python3 ingest/fetch_all.py
/home/goog/.local/bin/dbt run --quiet   # full path needed — dbt not on PATH in cron
```

### dbt models

**Bronze** (`main_bronze.*`) — Views directly over raw tables. No transform.

**Silver** (`main_silver.*`) — Incremental models. Type-cast strings to timestamps/doubles, deduplicate on unique keys:
- `stg_generation` — settlement_date + period + fuel_type
- `stg_prices` — valid_from (price_key)
- `stg_carbon_national` — period_from
- `stg_carbon` — regionid + loaded_at
- `stg_weather` — time

**Gold** (`main_gold.*`) — Materialised tables queried by the API:
- `mart_price_carbon` — full outer join of prices × carbon × generation
- `mart_best_windows` — top 10 future 30-min windows scored by combined price+carbon rank
- `mart_fuel_mix` — hourly generation by fuel type
- `mart_renewable_mix` — hourly renewable %, 7-day rolling avg
- `mart_regional_carbon` — current regional carbon with band labels
- `mart_price_heatmap` — avg price by hour_of_day × day_of_week
- `mart_carbon_heatmap` — avg carbon by hour_of_day × day_of_week (uses `loaded_at` as proxy for period time — inherent limitation of the regional API)
- `mart_solar_weather` — solar index, wind index from weather data (used by `/api/renewable-mix`)
- `mart_temp_vs_demand` — temperature vs grid demand (used by `/api/demand-profile` and `/api/kpi`)
- `mart_grid_stress` — hours flagged as high-carbon-risk

### Known data quirks

- **mart_price_carbon duplicate rows**: The full outer join creates duplicates when either prices or carbon have repeated ingest rows. Fix: always `GROUP BY period_utc, AVG()` in API queries. Do NOT use `LIMIT 1` without GROUP BY.
- **renewable_pct NULL for current period**: BMRS generation data has a ~30-min lag. The current half-hour has no generation data yet. Fix: `COALESCE(avg(p.renewable_pct), r.renewable_pct)` where `r` is the latest row from `mart_renewable_mix`.
- **Octopus prices**: Only 48h forward are fetched. Historical prices are in the DB from past ingests. Prices for times > 48h ahead will be NULL.
- **Weather API (Open-Meteo)**: Occasionally returns 502. When it does, the ingest skips the insert entirely — no rows written for that run. `stg_weather` handles `NULL` values from the API gracefully (no string `'None'` written to bronze).
- **No SOLAR in generation data**: BMRS transmission outturn doesn't include rooftop solar (embedded/behind-meter). Renewable % excludes solar by design.

---

## Database schemas

### Energy data (written by dbt)
- `main_bronze.*` — raw ingested rows
- `main_silver.*` — cleaned staging models
- `main_gold.*` — aggregated mart tables

---

## API endpoints

All endpoints are public — no authentication.

| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/now` | Current price, carbon, renewable%, score, recommendation, next best window |
| GET | `/api/windows-by-day` | Top 5 best 30-min windows for today + tomorrow, scored |
| GET | `/api/appliance-windows?hours=X` | Best windows for a sliding X-hour block |
| GET | `/api/prices-carbon` | Last 200 half-hourly price + carbon rows |
| GET | `/api/combined-heatmap` | Price+carbon score by hour_of_day × day_of_week |
| GET | `/api/best-windows` | Top 10 future windows from mart_best_windows |
| GET | `/api/fuel-mix` | Last 48h generation by fuel type |
| GET | `/api/renewable-mix` | Last 30 days renewable % + wind speed |
| GET | `/api/regional-carbon` | Current carbon by UK region |
| GET | `/api/demand-profile` | Avg demand by hour-of-day, weekday vs weekend |
| GET | `/api/grid-stress` | Last 7 days grid stress events |
| GET | `/api/kpi` | Summary KPIs (renewable peak, avg carbon, demand, current price) |

---

## Frontend (index.html)

Single HTML file (~1420 lines). Three tabs:

| Tab | Content | Loads when |
|-----|---------|------------|
| Dashboard | Hero signal, fuel mix donut + regional carbon, price/carbon chart, combined heatmap, demand profile, grid stress | Boot |
| Schedule | Appliance finder, best windows today/tomorrow | First visit (lazy) |
| About | Fuel type explainer, metrics glossary, data pipeline explanation | On click |

### Key JS functions

```
loadHero()              — fetches /api/now, renders hero signal widget
loadFuelMix()           — fetches /api/fuel-mix, renders stacked area chart
loadDonut()             — fetches /api/now + /api/regional-carbon, renders donut + map
loadRenewable()         — fetches /api/renewable-mix, renders renewable % chart
loadDemandProfile()     — fetches /api/demand-profile, renders demand chart
loadStress()            — fetches /api/grid-stress, renders stress timeline
loadWindowsByDay()      — fetches /api/windows-by-day, renders day-tab windows
showDay(day)            — switches today/tomorrow in best windows
fetchApplianceWindows() — fetches /api/appliance-windows, renders result cards
loadApplianceFinder()   — initial appliance finder setup
loadPriceCarbon()       — fetches /api/prices-carbon, renders price+carbon chart
loadCombinedHeatmap()   — fetches /api/combined-heatmap, renders heatmap grid
switchTab(name, btn)    — shows/hides tab panels; Schedule lazy-loads on first visit
```

---

## Scoring logic

**Window score (0–100):** Used in best windows, appliance finder, hero signal.
```
price_rank  = percent_rank() OVER (ORDER BY price ASC)   -- lower price = better rank
carbon_rank = percent_rank() OVER (ORDER BY carbon ASC)  -- lower carbon = better rank
score = (price_rank + carbon_rank) / 2 * 100
```

**Combined heatmap colour:**
```js
const hue = score < 50
  ? Math.round(score * 0.7)              // red (0°) → amber
  : Math.round(35 + (score - 50) * 1.7); // amber → green (120°)
return `hsl(${hue}, 88%, 36%)`;
```

---

## What's been built (history)

1. Light mode conversion
2. Consumer UI redesign: hero signal, appliance finder, best windows
3. Mobile CSS
4. Data pipeline fix: dbt full path in run_pipeline.sh
5. Octopus prices fix: 48h forward with explicit period_from/period_to
6. Renewable % fallback for current period (30-min BMRS lag)
7. Duplicate rows fix: GROUP BY + AVG in all API endpoints
8. Donut chart redesign with center GW + renewable %
9. Interconnectors collapsed to single "Connections" entry in fuel mix
10. Combined price+carbon heatmap (replaced two correlated charts)
11. stg_weather NULL safety: weather API None values no longer crash dbt cast
12. fetch_all.py refactored into main() — safe to import, no module-level side effects
13. combined_score removed from mart_price_carbon / mart_best_windows (dead computation)

---

## Potential next steps

- **Deployment**: Railway or Fly.io. Cron via platform scheduler or GitHub Actions.
- **User accounts**: bcrypt + session cookies in DuckDB (login/signup templates exist, no backend yet)
- **Alerts**: Email or HA webhook when price/carbon drops below threshold
- **Savings tracker**: Log appliance runs, compare actual Agile cost vs daily avg
- **Push notifications**: Web Push API (pywebpush + VAPID keys + service worker)
- **Tariff comparison**: "Would you save on Agile vs your flat rate?"
- **Daily digest email**: Cron job sending tomorrow's best windows each evening
- **Solar generation**: Factor export tariff into advice for users with panels
- **Multiple locations**: Currently hardcoded to Birmingham (52.48°N, 1.90°W) for weather
