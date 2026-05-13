# UK Energy Grid Dashboard

A smart energy dashboard for UK EV owners and smart home users. Shows live grid data — Agile price, carbon intensity, and generation mix — and finds the cheapest, cleanest windows to run appliances.

<img src="docs/screenshots/01-dashboard.png" width="100%" alt="Dashboard" />

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Data Pipeline](#data-pipeline)
- [Architecture](#architecture)
- [API Reference](#api-reference)
- [Deployment](#deployment)
- [Troubleshooting](#troubleshooting)

---

## Features

- **Live grid signal** — current Agile price (p/kWh), carbon intensity (gCO₂/kWh), renewable %, and a 0–100 "go now" score, updated every 30 minutes
- **Appliance scheduler** — pick an appliance and duration; the app finds the cheapest, cleanest window across the next 48 hours
- **Best windows by day** — top 5 half-hour slots for today and tomorrow, ranked by combined price + carbon score
- **Generation mix** — live donut chart and fuel-group breakdown (renewables, fossil, interconnectors)
- **Charts** — price/carbon timeline, hour × day-of-week heatmap, regional carbon map, renewable % trend, solar/wind index, temperature vs demand scatter
- **Mobile-responsive** — works on phones and tablets

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python 3.12), uvicorn |
| Database | DuckDB (single embedded file) |
| Data pipeline | dbt-core + dbt-duckdb |
| Frontend | Vanilla JS + Chart.js 4.4, server-rendered HTML |

No Node.js. No React. No auth provider. No database server.

---

## Prerequisites

- Python 3.12+
- `pip` (system or virtualenv)
- Internet access for the four upstream APIs (all free, no API keys required)

DuckDB is embedded — nothing else to install or run.

---

## Getting Started

### 1. Clone

```bash
git clone https://github.com/YOUR_USERNAME/uk-energy-grid.git
cd uk-energy-grid
```

### 2. Install dependencies

```bash
pip install -r requirements.txt --break-system-packages
```

If you prefer a virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Run the data pipeline (first-time seed)

Fetches live data from the four UK grid APIs and builds the DuckDB database:

```bash
bash run_pipeline.sh
```

Runs `ingest/fetch_all.py` then `dbt run`. On a clean checkout this creates `energy.duckdb` from scratch — expect 10–20 seconds.

> **Keep data fresh:** Schedule this every 30 minutes via cron:
> ```
> */30 * * * * cd /path/to/uk-energy-grid && bash run_pipeline.sh
> ```

### 4. Start the app

```bash
python3 dashboard/app.py
```

Or with auto-reload during development:

```bash
python3 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000 --reload
```

Open [http://localhost:8000](http://localhost:8000).

---

## Screenshots

**Dashboard** — live signal, generation mix, price & carbon chart

<img src="docs/screenshots/01-dashboard.png" width="100%" alt="Dashboard" />

**Schedule** — appliance finder and best 30-minute windows

<img src="docs/screenshots/02-schedule.png" width="100%" alt="Schedule tab" />

**Mobile**

<img src="docs/screenshots/05-mobile.png" width="390" alt="Mobile view" />

---

## Environment Variables

Only one variable is needed. The app runs without it — the database is created in the working directory by default.

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENERGY_DB_PATH` | `./energy.duckdb` | Path to DuckDB file |

---

## Data Pipeline

### Sources

| Source | Data | Cadence |
|--------|------|---------|
| [Elexon BMRS](https://bmrs.elexon.co.uk/) | Half-hourly generation by fuel type | 30 min |
| [Open-Meteo](https://open-meteo.com/) | Hourly weather — Birmingham (52.48°N, 1.90°W) | 30 min |
| [Carbon Intensity API](https://carbonintensity.org.uk/) | National + regional carbon intensity & 48h forecast | 30 min |
| [Octopus Energy API](https://developer.octopus.energy/) | Agile half-hourly prices (48h forward) | 30 min |

All APIs are free and require no authentication.

### dbt layers

```
bronze/   → raw views directly over ingested tables (no transform)
silver/   → incremental models: type-cast, deduplicate
gold/     → materialised mart tables queried by the API
```

Key gold tables:

| Table | Purpose |
|-------|---------|
| `mart_price_carbon` | Prices × carbon × generation, joined by half-hour period |
| `mart_best_windows` | Top 10 future windows scored by price + carbon rank |
| `mart_fuel_mix` | Hourly generation by fuel type |
| `mart_renewable_mix` | Hourly renewable %, 7-day rolling average |
| `mart_regional_carbon` | Current carbon intensity for all 14 UK regions |
| `mart_price_heatmap` | Average price by hour-of-day × day-of-week |
| `mart_solar_weather` | Solar index, wind index derived from weather data |

### Scoring

Window score (0–100) used in the appliance finder and hero signal:

```
price_rank  = percent_rank() OVER (ORDER BY price ASC)
carbon_rank = percent_rank() OVER (ORDER BY carbon ASC)
score       = (price_rank + carbon_rank) / 2 × 100
```

Higher score = cheaper **and** cleaner.

---

## Architecture

```
uk-energy-grid/
├── dashboard/
│   ├── app.py                  ← FastAPI app — all backend logic
│   └── templates/
│       └── index.html          ← Single-page app (3 tabs, charts, JS)
├── ingest/
│   └── fetch_all.py            ← Pulls from 4 APIs → bronze tables
├── models/
│   ├── bronze/                 ← dbt views over raw tables
│   ├── silver/                 ← dbt incremental: cast + dedupe
│   └── gold/                   ← dbt materialised marts
├── seeds/
│   └── region_lookup.csv       ← regionid → region name
├── energy.duckdb               ← Embedded database (gitignored)
├── run_pipeline.sh             ← Ingest + dbt; run by cron
├── requirements.txt
├── dbt_project.yml
└── profiles.yml                ← dbt profile (reads ENERGY_DB_PATH)
```

### Request flow

```
Browser → FastAPI route → DuckDB query (gold marts) → JSON → Chart.js render
```

The frontend is a single `index.html` file. Vanilla JS, no build step. Three tabs:

| Tab | Content |
|-----|---------|
| **Dashboard** | Hero signal, generation mix donut, fuel breakdown, price/carbon chart, heatmap, advanced charts |
| **Schedule** | Appliance finder, best 30-min windows for today / tomorrow |
| **About** | Fuel type explainer, metrics glossary, data sources |

### Database schema

All data is written by the dbt pipeline into DuckDB:

```
main_bronze.*   — raw ingested rows (views)
main_silver.*   — cleaned, deduplicated staging models
main_gold.*     — aggregated mart tables queried by the API
```

---

## API Reference

All endpoints are public — no authentication required.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/now` | Current price, carbon, renewable %, score, next best window |
| `GET` | `/api/windows-by-day` | Top 5 windows for today + tomorrow |
| `GET` | `/api/appliance-windows?hours=X` | Best windows for an X-hour appliance block |
| `GET` | `/api/prices-carbon` | Last 200 half-hourly price + carbon rows |
| `GET` | `/api/combined-heatmap` | Price+carbon score by hour × day-of-week |
| `GET` | `/api/best-windows` | Top 10 future windows |
| `GET` | `/api/fuel-mix` | Last 48h generation by fuel type |
| `GET` | `/api/renewable-mix` | Last 30 days renewable % + weather |
| `GET` | `/api/regional-carbon` | Current carbon intensity by UK region |
| `GET` | `/api/solar-weather` | Solar/wind index + weather data |
| `GET` | `/api/temp-vs-demand` | Temperature vs grid demand scatter data |
| `GET` | `/api/demand-profile` | Average demand by hour-of-day, weekday vs weekend |
| `GET` | `/api/grid-stress` | Last 7 days grid stress events |
| `GET` | `/api/interconnectors` | Last 48h interconnector flows |
| `GET` | `/api/kpi` | Summary KPIs |

---

## Deployment

The app is a single Python process with an embedded database — no database server, message queue, or cache layer needed.

### Railway / Fly.io / Render

1. Push to GitHub
2. Connect repo to your platform
3. Set start command: `python3 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000`
4. Optionally set `ENERGY_DB_PATH` to point at a persistent volume
5. Add a scheduled job to run `bash run_pipeline.sh` every 30 minutes

> **Persistent storage:** DuckDB writes to a local file. On platforms with ephemeral filesystems (Fly.io, Render free tier), mount a persistent volume and set `ENERGY_DB_PATH` to that path.

### VPS / bare metal

```bash
# Clone and install
git clone https://github.com/YOUR_USERNAME/uk-energy-grid.git
cd uk-energy-grid
pip install -r requirements.txt --break-system-packages

# Seed data
bash run_pipeline.sh

# Example systemd unit: /etc/systemd/system/ukenergy.service
[Unit]
Description=UK Energy Grid Dashboard
After=network.target

[Service]
WorkingDirectory=/opt/uk-energy-grid
ExecStart=python3 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000
Restart=always
Environment=ENERGY_DB_PATH=/opt/uk-energy-grid/energy.duckdb

[Install]
WantedBy=multi-user.target

# Enable and start
sudo systemctl enable ukenergy
sudo systemctl start ukenergy

# Cron for pipeline
crontab -e
# */30 * * * * cd /opt/uk-energy-grid && bash run_pipeline.sh
```

---

## Troubleshooting

**Empty dashboard / no data**

Run the pipeline manually and check for errors:
```bash
bash run_pipeline.sh
```
All four data sources are external — check API availability if it fails. The Octopus Agile endpoint only publishes prices 48h ahead; periods beyond that will show `null`.

**`energy.duckdb` not found**

The database is created by `run_pipeline.sh` on first run. Run the pipeline before starting the app.

**dbt not found when running pipeline**

dbt installs to `~/.local/bin/` which may not be on `PATH` in cron. The pipeline script uses the full path. If your install location differs, update `run_pipeline.sh`:
```bash
which dbt   # find the actual path
```

**Port already in use**

```bash
lsof -i :8000
kill -9 <PID>
```

**Duplicate rows in API responses**

All gold mart queries use `GROUP BY period_utc, AVG()` to handle duplicates from the full-outer-join in `mart_price_carbon`. If writing custom queries, always group rather than using `LIMIT 1`.

---

## Data Sources & Attribution

- **Elexon BMRS** — Contains BMRS data © Elexon Ltd
- **Carbon Intensity API** — National Grid ESO, University of Oxford, WWF
- **Open-Meteo** — CC BY 4.0
- **Octopus Energy API** — Octopus Energy Ltd

---

## License

MIT
