import os
import json
import duckdb
import requests
from datetime import datetime, timezone, timedelta

DB_PATH = os.environ.get(
    'ENERGY_DB_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'energy.duckdb')
)

con = duckdb.connect(DB_PATH)

con.execute("create schema if not exists bronze")

con.execute("""
    create table if not exists bronze.raw_generation (
        settlement_date   varchar,
        settlement_period integer,
        fuel_type         varchar,
        generation        varchar,
        loaded_at         timestamp default current_timestamp
    )
""")

con.execute("""
    create table if not exists bronze.raw_weather (
        time           varchar,
        temperature_2m varchar,
        windspeed_10m  varchar,
        loaded_at      timestamp default current_timestamp
    )
""")

# Extend raw_weather with new columns if not present
for col in [
    "cloudcover varchar",
    "direct_radiation varchar",
    "wind_direction_10m varchar",
    "precipitation varchar",
]:
    try:
        con.execute(f"alter table bronze.raw_weather add column if not exists {col}")
    except Exception:
        pass

con.execute("""
    create table if not exists bronze.raw_prices (
        valid_from    varchar,
        valid_to      varchar,
        value_inc_vat double,
        product_code  varchar,
        loaded_at     timestamp default current_timestamp
    )
""")

con.execute("""
    create table if not exists bronze.raw_carbon_national (
        from_time         varchar,
        to_time           varchar,
        intensity_actual  varchar,
        intensity_forecast varchar,
        intensity_index   varchar,
        loaded_at         timestamp default current_timestamp
    )
""")

con.execute("""
    create table if not exists bronze.raw_carbon (
        regionid         varchar,
        shortname        varchar,
        intensity_actual varchar,
        generationmix    varchar,
        loaded_at        timestamp default current_timestamp
    )
""")

results = {}

# --- Elexon BMRS ---
# Response: list of {startTime, settlementPeriod, data: [{fuelType, generation}]}
try:
    today = datetime.now(timezone.utc).date().isoformat()
    r = requests.get(
        'https://data.elexon.co.uk/bmrs/api/v1/generation/outturn/summary',
        params={'settlementDateFrom': today, 'settlementDateTo': today, 'format': 'json'},
        timeout=30,
    )
    r.raise_for_status()
    periods = r.json() if isinstance(r.json(), list) else r.json().get('data', [])
    count = 0
    for period in periods:
        settlement_date = period['startTime'][:10]
        settlement_period = period['settlementPeriod']
        for fuel in period.get('data', []):
            con.execute(
                "insert into bronze.raw_generation values (?,?,?,?,current_timestamp)",
                [settlement_date, settlement_period, fuel['fuelType'], str(fuel['generation'])]
            )
            count += 1
    results['generation'] = f"OK — {count} rows"
except Exception as e:
    results['generation'] = f"ERROR — {e}"

# --- Open-Meteo ---
try:
    r = requests.get(
        'https://api.open-meteo.com/v1/forecast',
        params={
            'latitude': 52.48,
            'longitude': -1.90,
            'hourly': 'temperature_2m,windspeed_10m,cloudcover,direct_radiation,precipitation,wind_direction_10m',
            'past_days': 1,
            'forecast_days': 1,
        },
        timeout=30,
    )
    r.raise_for_status()
    hourly = r.json()['hourly']
    rows = list(zip(
        hourly['time'],
        hourly['temperature_2m'],
        hourly['windspeed_10m'],
        hourly['cloudcover'],
        hourly['direct_radiation'],
        hourly['wind_direction_10m'],
        hourly['precipitation'],
    ))
    for t, temp, wind, cld, rad, wdir, precip in rows:
        con.execute(
            "insert into bronze.raw_weather(time,temperature_2m,windspeed_10m,cloudcover,direct_radiation,wind_direction_10m,precipitation,loaded_at) values (?,?,?,?,?,?,?,current_timestamp)",
            [t, str(temp), str(wind), str(cld), str(rad), str(wdir), str(precip)]
        )
    results['weather'] = f"OK — {len(rows)} rows"
except Exception as e:
    results['weather'] = f"ERROR — {e}"

# --- Carbon Intensity ---
try:
    r = requests.get(
        'https://api.carbonintensity.org.uk/regional',
        headers={'Accept': 'application/json'},
        timeout=30,
    )
    r.raise_for_status()
    count = 0
    for entry in r.json().get('data', []):
        for region in entry.get('regions', []):
            con.execute(
                "insert into bronze.raw_carbon values (?,?,?,?,current_timestamp)",
                [
                    str(region['regionid']),
                    region['shortname'],
                    str(region['intensity'].get('actual') or region['intensity'].get('forecast')),
                    json.dumps(region.get('generationmix', [])),
                ]
            )
            count += 1
    results['carbon'] = f"OK — {count} rows"
except Exception as e:
    results['carbon'] = f"ERROR — {e}"

# --- Octopus Agile Prices ---
try:
    # Discover current Agile product code dynamically
    r = requests.get('https://api.octopus.energy/v1/products/',
        params={'is_variable': 'true', 'page_size': 100}, timeout=15)
    r.raise_for_status()
    agile_products = [p for p in r.json().get('results', [])
                      if 'AGILE' in p['code']
                      and p.get('direction', 'IMPORT') == 'IMPORT'
                      and not p.get('is_prepay', False)]
    if not agile_products:
        raise ValueError("No Agile product found")
    product_code = sorted(agile_products, key=lambda p: p['code'], reverse=True)[0]['code']
    tariff_code = f"E-1R-{product_code}-C"

    now = datetime.now(timezone.utc)
    period_from = now.strftime('%Y-%m-%dT%H:%M:%SZ')
    period_to   = (now + timedelta(hours=48)).strftime('%Y-%m-%dT%H:%M:%SZ')
    r = requests.get(
        f'https://api.octopus.energy/v1/products/{product_code}/electricity-tariffs/{tariff_code}/standard-unit-rates/',
        params={'page_size': 200, 'period_from': period_from, 'period_to': period_to},
        timeout=15)
    r.raise_for_status()
    rates = r.json().get('results', [])
    count = 0
    for rate in rates:
        con.execute(
            "insert into bronze.raw_prices values (?,?,?,?,current_timestamp)",
            [rate['valid_from'], rate['valid_to'], rate['value_inc_vat'], product_code]
        )
        count += 1
    results['prices'] = f"OK — {count} rates ({product_code})"
except Exception as e:
    results['prices'] = f"ERROR — {e}"

# --- Carbon Intensity (National + Forecast) ---
try:
    now = datetime.now(timezone.utc)
    future = now + timedelta(hours=48)
    url = (f"https://api.carbonintensity.org.uk/intensity/"
           f"{now.strftime('%Y-%m-%dT%H:%MZ')}/"
           f"{future.strftime('%Y-%m-%dT%H:%MZ')}")
    r = requests.get(url, headers={'Accept': 'application/json'}, timeout=15)
    r.raise_for_status()
    rows = r.json().get('data', [])
    count = 0
    for row in rows:
        intensity = row.get('intensity', {})
        con.execute(
            "insert into bronze.raw_carbon_national values (?,?,?,?,?,current_timestamp)",
            [row['from'], row['to'],
             str(intensity.get('actual') or ''),
             str(intensity.get('forecast') or ''),
             str(intensity.get('index') or '')]
        )
        count += 1
    results['carbon_national'] = f"OK — {count} rows"
except Exception as e:
    results['carbon_national'] = f"ERROR — {e}"

print(f"Ingest complete: {datetime.now(timezone.utc).isoformat()}")
for source, status in results.items():
    print(f"  {source:12s} {status}")

con.close()
