# UK Energy Grid Dashboard

A consumer-facing smart energy dashboard for UK EV owners and smart home users. Shows live grid data — price, carbon intensity, and generation mix — and finds the cheapest, cleanest windows to run appliances. Includes user accounts, price/carbon alerts, and a savings tracker.

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

- **Live grid signal** — current Agile price (p/kWh), carbon intensity (gCO₂/kWh), renewable %, and a 0–100 "go now" score updated every 30 minutes
- **Appliance scheduler** — pick an appliance and duration; the app finds the cheapest, cleanest window across the next 48 hours
- **Best windows by day** — top 5 slots for today and tomorrow ranked by combined price + carbon score
- **Charts** — price/carbon timeline, generation fuel mix donut, heatmap by hour-of-day and day-of-week, regional carbon map, renewable % trend, solar/wind index, temperature vs demand scatter
- **Price & carbon alerts** — email notifications with quiet hours and 2-hour cooldown; optional Home Assistant webhook
- **Savings tracker** — log EV charges or appliance runs; auto-calculates actual cost from live Agile prices vs daily average baseline
- **User accounts** — bcrypt auth, 30-day session cookies, tariff settings (Agile or flat rate)
- **Mobile-responsive** — works on phones and tablets

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (Python 3.12), uvicorn |
| Database | DuckDB (single file) |
| Data pipeline | dbt-core + dbt-duckdb |
| Frontend | Vanilla JS + Chart.js 4.4, server-rendered HTML |
| Auth | bcrypt (passlib) + session tokens |
| Email alerts | smtplib (STARTTLS) |
| HA integration | HTTP POST to user-configured webhook |

No Node.js build step. No React. No external auth provider.

---

## Prerequisites

- Python 3.12+
- `pip` (system or virtualenv)
- Internet access for the four upstream APIs (no API keys required — all are free/open)

That's it. DuckDB is embedded; no database server to install or run.

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

This fetches live data from the four UK grid APIs and builds the DuckDB database:

```bash
bash run_pipeline.sh
```

The pipeline runs `ingest/fetch_all.py` followed by `dbt run`. On a clean checkout it creates `energy.duckdb` from scratch. Expect it to take 10–20 seconds.

> **Cron:** To keep data fresh, schedule this to run every 30 minutes:
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

All variables are optional — the app runs with defaults out of the box.

| Variable | Default | Purpose |
|----------|---------|---------|
| `ENERGY_DB_PATH` | `./energy.duckdb` | Path to DuckDB file |
| `SMTP_HOST` | `smtp.gmail.com` | Email server hostname |
| `SMTP_PORT` | `587` | Email port (STARTTLS) |
| `SMTP_USER` | *(unset)* | Gmail address for alert emails |
| `SMTP_PASS` | *(unset)* | App password — if unset, alerts log to console only |

To enable email alerts, create a `.env` file (or export the vars):

```bash
SMTP_USER=you@gmail.com
SMTP_PASS=your-app-password   # Google → Security → App Passwords
```

---

## Data Pipeline

### Sources

| Source | Data | Refresh cadence |
|--------|------|----------------|
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
│       ├── index.html          ← Single-page app (tabs, charts, JS)
│       ├── login.html
│       └── signup.html
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
Browser → FastAPI route → DuckDB query (gold marts) → JSON response → Chart.js render
```

The frontend is a single `index.html` file (~2,400 lines). It uses vanilla JS with no build step — tabs lazy-load their data on first visit, everything else loads at boot.

### Alert background task

`_alert_checker_loop()` runs as an asyncio task inside the FastAPI lifespan. Every 30 minutes it:

1. Reads current grid state from `/api/now`
2. Checks all enabled user alerts against their thresholds
3. Respects 2-hour cooldown (`last_fired_at`) and quiet hours
4. Sends email via SMTP if configured; always fires HA webhook if set

### Database schemas

**Energy data** (written by dbt): `main_bronze.*`, `main_silver.*`, `main_gold.*`

**App data** (written by FastAPI, in `app` schema):

```sql
app.users           -- id, email, password_hash (bcrypt), created_at
app.user_sessions   -- token, user_id, expires_at (30 days)
app.user_alerts     -- alert_type, threshold, quiet_from/to, last_fired_at
app.user_settings   -- tariff_type, flat_rate, ha_webhook_url
app.usage_log       -- device_name, kwh, cost_actual, cost_optimal
```

---

## API Reference

### Public endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/now` | Current price, carbon, renewable %, score, next best window |
| `GET` | `/api/windows-by-day` | Top 5 windows for today + tomorrow |
| `GET` | `/api/appliance-windows?hours=X` | Best windows for an X-hour block |
| `GET` | `/api/prices-carbon` | Last 200 half-hourly price + carbon rows |
| `GET` | `/api/combined-heatmap` | Price+carbon score by hour × day-of-week |
| `GET` | `/api/best-windows` | Top 10 future windows |
| `GET` | `/api/fuel-mix` | Last 48h generation by fuel type |
| `GET` | `/api/renewable-mix` | Last 30 days renewable % + weather |
| `GET` | `/api/regional-carbon` | Current carbon by UK region |
| `GET` | `/api/kpi` | Summary KPIs |

### Auth-gated endpoints (require `session` cookie)

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/alerts` | List user's alerts |
| `POST` | `/api/alerts` | Create alert |
| `PATCH` | `/api/alerts/{id}/toggle` | Enable/disable alert |
| `GET` | `/api/savings` | Last 50 charge logs |
| `POST` | `/api/savings` | Log a new charge |
| `GET` | `/api/savings/summary` | Total/weekly/monthly savings |
| `GET/POST` | `/api/settings` | Get or update tariff + HA webhook |

---

## Deployment

The app is a single Python process with an embedded database — no separate database server, no message queue, no cache layer needed.

### Railway / Fly.io / Render

1. Push to GitHub
2. Connect repo to your platform
3. Set start command: `python3 -m uvicorn dashboard.app:app --host 0.0.0.0 --port 8000`
4. Set environment variables (`SMTP_USER`, `SMTP_PASS`, optionally `ENERGY_DB_PATH`)
5. Add a scheduled job (cron) to run `bash run_pipeline.sh` every 30 minutes

> **Note on DuckDB and persistent storage:** DuckDB writes to a local file. On platforms with ephemeral filesystems (Fly.io, Render free tier), mount a persistent volume at the path set by `ENERGY_DB_PATH`. On Railway, use a volume or switch to the managed PostgreSQL addon with a DuckDB-compatible layer.

### VPS / bare metal

```bash
# Clone and install
git clone https://github.com/YOUR_USERNAME/uk-energy-grid.git
cd uk-energy-grid
pip install -r requirements.txt --break-system-packages

# Seed data
bash run_pipeline.sh

# Run via systemd (example unit file)
# /etc/systemd/system/ukenergy.service
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

# Add cron for pipeline
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
If the pipeline fails, check API availability — all four sources are external. The Octopus Agile endpoint only publishes prices 48h ahead; historical periods beyond that will show `null`.

**`energy.duckdb` not found**

The database is created by `run_pipeline.sh` on first run. Make sure you run the pipeline before starting the app.

**dbt not found when running pipeline**

dbt installs to `~/.local/bin/` which may not be on `PATH` in cron. The pipeline script uses the full path `/home/$USER/.local/bin/dbt`. If your install location differs, update `run_pipeline.sh` accordingly.

**Port already in use**

```bash
lsof -i :8000
kill -9 <PID>
```

**SMTP alerts not sending**

- Confirm `SMTP_USER` and `SMTP_PASS` are set
- Use a [Google App Password](https://support.google.com/accounts/answer/185833), not your main Gmail password
- Check `pipeline.log` — alert fire attempts are logged there

**Duplicate rows in API responses**

All gold mart queries use `GROUP BY period_utc, AVG()` to handle the full-outer-join duplicates in `mart_price_carbon`. If you write custom queries, always group rather than using `LIMIT 1`.

---

## Data Sources & Attribution

- **Elexon BMRS** — Contains BMRS data © Elexon Ltd
- **Carbon Intensity API** — National Grid ESO, University of Oxford, WWF
- **Open-Meteo** — CC BY 4.0
- **Octopus Energy API** — Octopus Energy Ltd

---

## License

MIT
