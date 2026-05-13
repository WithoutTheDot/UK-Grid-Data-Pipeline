# UK Energy Grid — Project Handoff

Consumer-facing smart energy dashboard for UK EV owners and smart home users.
Shows live grid data (price, carbon, generation mix) and helps users find the
cheapest, cleanest times to run appliances. Has user accounts, alerts, and a
savings tracker.

---

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI (Python 3.12), served via uvicorn |
| Database | DuckDB (single file: `energy.duckdb`) |
| Data pipeline | dbt-core + dbt-duckdb |
| Frontend | Vanilla JS + Chart.js 4.4, server-rendered HTML |
| Auth | bcrypt (passlib) + session tokens in DuckDB |
| Email | smtplib (SMTP_USER / SMTP_PASS env vars) |
| HA integration | urllib HTTP POST to user-configured webhook URL |

No Node.js. No React. No external auth provider.

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
| `SMTP_HOST` | `smtp.gmail.com` | Email server |
| `SMTP_PORT` | `587` | Email port (STARTTLS) |
| `SMTP_USER` | *(empty)* | Gmail address (or other) |
| `SMTP_PASS` | *(empty)* | App password — if unset, alerts log to console only |

---

## Project structure

```
UKEngergy/
├── dashboard/
│   ├── app.py                  ← FastAPI app — ALL backend logic lives here
│   └── templates/
│       ├── index.html          ← Single-page app (tabs, charts, JS)
│       ├── login.html          ← Login page
│       └── signup.html         ← Signup page
├── ingest/
│   └── fetch_all.py            ← Pulls from 4 APIs, writes to bronze tables
├── models/
│   ├── bronze/                 ← dbt views over raw tables (no transform)
│   ├── silver/                 ← dbt incremental models: type-cast, dedupe
│   └── gold/                   ← dbt tables: joined, aggregated, query-ready
├── seeds/
│   └── region_lookup.csv       ← Maps Carbon Intensity regionid → full name
├── energy.duckdb               ← Single database file (all schemas)
├── run_pipeline.sh             ← Runs fetch_all.py + dbt; called by cron
├── requirements.txt
├── dbt_project.yml
└── profiles.yml                ← dbt profile (reads ENERGY_DB_PATH)
```

---

## Data pipeline

### Ingest (`ingest/fetch_all.py`)

Runs every 30 minutes (cron or manual). Pulls from four APIs:

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
- `mart_price_carbon` — full outer join of prices × carbon × generation. Has duplicate rows per period (from the full outer join pattern) — all API queries GROUP BY period_utc + AVG() to deduplicate
- `mart_best_windows` — top 10 future 30-min windows scored by combined price+carbon rank
- `mart_fuel_mix` — hourly generation by fuel type
- `mart_renewable_mix` — hourly renewable %, 7-day rolling avg
- `mart_regional_carbon` — current regional carbon with band labels
- `mart_price_heatmap` — avg price by hour_of_day × day_of_week
- `mart_carbon_heatmap` — avg carbon by hour_of_day × day_of_week
- `mart_solar_weather` — solar index, wind index from weather data
- `mart_temp_vs_demand` — temperature vs grid demand for scatter chart
- `mart_grid_stress` — hours flagged as high-carbon-risk

### Known data quirks

- **mart_price_carbon duplicate rows**: The full outer join creates duplicates when either prices or carbon have repeated ingest rows. Fix: always `GROUP BY period_utc, AVG()` in API queries. Do NOT use `LIMIT 1` without GROUP BY.
- **renewable_pct NULL for current period**: BMRS generation data has a ~30-min lag. The current half-hour has no generation data yet. Fix: `COALESCE(avg(p.renewable_pct), r.renewable_pct)` where `r` is the latest row from `mart_renewable_mix`.
- **Octopus prices**: Only 48h forward are fetched. Historical prices are in the DB from past ingests. Prices for times > 48h ahead will be NULL.

---

## Database schemas

### Energy data (written by dbt)
- `main_bronze.*` — raw ingested rows
- `main_silver.*` — cleaned staging models
- `main_gold.*` — aggregated mart tables

### App data (written by FastAPI, in `app` schema)

```sql
app.users (
    id            VARCHAR PRIMARY KEY,   -- uuid4
    email         VARCHAR UNIQUE,
    password_hash VARCHAR,              -- bcrypt
    created_at    TIMESTAMP
)

app.user_sessions (
    token      VARCHAR PRIMARY KEY,     -- secrets.token_urlsafe(32)
    user_id    VARCHAR,
    expires_at TIMESTAMP,              -- 30 days from login
    created_at TIMESTAMP
)

app.user_alerts (
    id            VARCHAR PRIMARY KEY,
    user_id       VARCHAR,
    alert_type    VARCHAR,             -- 'price_below' | 'carbon_below' | 'good_window'
    threshold     DOUBLE,             -- p/kWh | gCO₂/kWh | score 0-100
    label         VARCHAR,            -- human-readable description
    enabled       BOOLEAN,
    last_fired_at TIMESTAMP,          -- used for 2h cooldown
    quiet_from    INTEGER,            -- hour 0-23, NULL = no quiet hours
    quiet_to      INTEGER,
    created_at    TIMESTAMP
)

app.user_settings (
    user_id        VARCHAR PRIMARY KEY,
    tariff_type    VARCHAR,           -- 'agile' | 'flat'
    flat_rate      DOUBLE,            -- p/kWh (only used when tariff_type = 'flat')
    ha_webhook_url VARCHAR,           -- Home Assistant webhook URL
    updated_at     TIMESTAMP
)

app.usage_log (
    id           VARCHAR PRIMARY KEY,
    user_id      VARCHAR,
    device_name  VARCHAR,
    start_time   TIMESTAMP,
    duration_h   DOUBLE,
    kwh          DOUBLE,             -- duration_h * kw_rating
    cost_actual  DOUBLE,             -- £ — avg Agile price for window * kwh / 100
    cost_optimal DOUBLE,             -- £ — daily avg price * kwh / 100 (comparison baseline)
    logged_at    TIMESTAMP
)
```

---

## API endpoints

### Public (no auth)
| Method | Path | Returns |
|--------|------|---------|
| GET | `/api/now` | Current price, carbon, renewable%, score, recommendation, next best window |
| GET | `/api/windows-by-day` | Top 5 best 30-min windows for today + tomorrow, scored |
| GET | `/api/appliance-windows?hours=X` | Best windows for a sliding X-hour block |
| GET | `/api/prices-carbon` | Last 200 half-hourly price + carbon rows |
| GET | `/api/combined-heatmap` | Price+carbon score by hour_of_day × day_of_week |
| GET | `/api/best-windows` | Top 10 future windows from mart_best_windows |
| GET | `/api/fuel-mix` | Last 48h generation by fuel type |
| GET | `/api/renewable-mix` | Last 30 days renewable % + weather |
| GET | `/api/regional-carbon` | Current carbon by UK region |
| GET | `/api/solar-weather` | Last 4 days solar/wind/weather data |
| GET | `/api/temp-vs-demand` | Scatter data: temperature vs grid demand |
| GET | `/api/demand-profile` | Avg demand by hour-of-day, weekday vs weekend |
| GET | `/api/grid-stress` | Last 7 days grid stress events |
| GET | `/api/interconnectors` | Last 48h interconnector flows |
| GET | `/api/kpi` | Summary KPIs (renewable peak, avg carbon, demand) |

### Auth
| Method | Path | Notes |
|--------|------|-------|
| GET | `/login` | Login page |
| GET | `/signup` | Signup page |
| POST | `/auth/login` | Form: email, password → sets `session` cookie, redirects `/` |
| POST | `/auth/signup` | Form: email, password → creates user, sets cookie, redirects `/` |
| POST | `/auth/logout` | Clears cookie, redirects `/login` |
| GET | `/api/me` | `{authenticated, email, id, smtp_configured}` |
| POST | `/api/auth/change-password` | Form: new_password, confirm_password |

### User data (require `session` cookie)
| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/alerts` | List user's alerts |
| POST | `/api/alerts` | Form: alert_type, threshold, quiet_from, quiet_to |
| DELETE | `/api/alerts/{id}` | Delete alert |
| PATCH | `/api/alerts/{id}/toggle` | Toggle enabled |
| POST | `/api/alerts/check` | Manually trigger alert check |
| GET | `/api/savings` | List last 50 logged charges |
| POST | `/api/savings` | Form: device_name, start_time, duration_h, kw_rating |
| DELETE | `/api/savings/{id}` | Delete a log entry |
| GET | `/api/savings/summary` | `{total_saving, week_saving, month_saving, total_charges}` |
| GET | `/api/settings` | Get user settings |
| POST | `/api/settings` | Form: tariff_type, flat_rate, ha_webhook_url |
| POST | `/api/settings/test-webhook` | Fire a test POST to the saved HA webhook |

---

## Frontend (index.html)

Single HTML file (~2400 lines). Six tabs:

| Tab | Content | Loads when |
|-----|---------|------------|
| Dashboard | Hero signal, grid snapshot (donut + regional), price/carbon chart, combined heatmap, advanced panel | Boot |
| Schedule | Appliance finder, best windows today/tomorrow | First visit (lazy) |
| Alerts | Alert management UI (auth-gated) | Boot (empty if not logged in) |
| Savings | Charge logger, history, summaries (auth-gated) | Boot |
| Settings | Tariff, HA webhook, change password (auth-gated) | Boot |
| About | Fuel type explainer, metrics glossary, data pipeline explanation | On click |

### Key JS functions

```
loadMe()           — fetches /api/me, shows/hides auth-gated panels, loads user data
loadHero()         — fetches /api/now, renders hero signal widget
loadWindowsByDay() — fetches /api/windows-by-day, renders day-tab windows
loadApplianceFinder() — initial fetch for appliance windows
fetchApplianceWindows(hours, kw, label) — renders appliance result cards
loadAlerts()       — fetches /api/alerts, renders alert cards
loadSavings()      — fetches /api/savings, renders charge history
loadSavingsSummary() — fetches /api/savings/summary, updates stat bar
loadSettings()     — fetches /api/settings, populates settings form
saveSettings()     — POSTs /api/settings
switchTab(name, btn) — shows/hides tab panels; Schedule lazy-loads on first visit
showDay(day)       — switches today/tomorrow in best windows
```

### Alert background checker

`_alert_checker_loop()` runs as an asyncio task in FastAPI lifespan.
Fires every 30 minutes. Checks all enabled alerts against current grid state.
Respects 2h cooldown (`last_fired_at`) and quiet hours (`quiet_from`/`quiet_to`).
If SMTP configured → sends email. Always tries HA webhook if URL is saved.

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
  ? Math.round(score * 0.7)            // red (0°) → amber
  : Math.round(35 + (score - 50) * 1.7); // amber → green (120°)
return `hsl(${hue}, 88%, 36%)`;
```

**Savings calculation:**
```
cost_actual  = avg(price_in_window) * kwh / 100   (£)
cost_at_avg  = avg(daily_price)     * kwh / 100   (£)
saving       = cost_at_avg - cost_actual           (£, positive = saved money)
```
Compared against daily average price, not worst-case, for honest numbers.

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
9. Interconnectors collapsed to single "Connections" entry
10. Combined price+carbon heatmap (replaced two correlated charts)
11. User accounts (bcrypt, session cookies)
12. Tab restructure: Dashboard / Schedule / Alerts / Savings / Settings / About
13. Alerts system: email + HA webhook, quiet hours, 2h cooldown
14. Savings tracker: auto-calculates cost from Agile prices, compares vs daily avg
15. Settings: tariff toggle, HA webhook, change password

---

## Potential next steps

- **Deployment**: Railway or Fly.io. Cron via platform scheduler or GitHub Actions.
- **Push notifications**: Web Push API (pywebpush + VAPID keys + service worker) — currently only email
- **Tariff comparison**: "Would you save on Agile vs your flat rate?" based on actual usage log
- **Saved appliances**: Let users persist custom appliance configs (name, hours, kW) in DB
- **Daily digest email**: Cron job sending tomorrow's best windows each evening
- **Historical savings chart**: Bar chart of weekly savings in the Savings tab
- **Solar generation**: If user has solar panels, factor export tariff into advice
- **Multiple locations**: Currently hardcoded to Birmingham (52.48°N, 1.90°W) for weather
