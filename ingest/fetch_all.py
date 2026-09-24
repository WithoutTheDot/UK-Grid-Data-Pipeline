import os
import json
import duckdb
import requests
from datetime import datetime, timezone, timedelta

DB_PATH = os.environ.get(
    'ENERGY_DB_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'energy.duckdb')
)

# Where the person using this lives. Change both if you're elsewhere.
# Weather: Birmingham. Octopus Agile prices vary by region, and Birmingham
# is region E (West Midlands); the letters are the DNO region codes Octopus uses.
LATITUDE, LONGITUDE = 52.48, -1.90
AGILE_REGION = 'E'

# Every run also re-pulls the last 24 hours, so a fresh database has some
# history to chart straight away and past slots get their final actual
# carbon figures instead of whatever forecast was stored at the time.
LOOKBACK = timedelta(hours=24)


def main():
    con = duckdb.connect(DB_PATH)
    try:
        _setup_schema(con)
        results = _ingest(con)
    finally:
        con.close()

    print(f"Ingest complete: {datetime.now(timezone.utc).isoformat()}")
    for source, status in results.items():
        print(f"  {source:16s} {status}")


def _setup_schema(con):
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
            time               varchar,
            temperature_2m     varchar,
            windspeed_10m      varchar,
            loaded_at          timestamp default current_timestamp
        )
    """)

    # start_time: the real UTC start of the half-hour, straight from BMRS.
    # Settlement periods count from UK local midnight, so the date + period
    # number alone is an hour out in summer.
    con.execute("alter table bronze.raw_generation add column if not exists start_time varchar")

    # Extra columns added after initial deploy — ALTER is idempotent
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
            from_time          varchar,
            to_time            varchar,
            intensity_actual   varchar,
            intensity_forecast varchar,
            intensity_index    varchar,
            loaded_at          timestamp default current_timestamp
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


def _ingest(con) -> dict:
    results = {}

    # Elexon BMRS FUELHH — half-hourly generation by fuel type. Unlike the
    # outturn summary endpoint it lists every fuel type in every period,
    # including interconnectors that are exporting (negative MW).
    try:
        now = datetime.now(timezone.utc)
        date_from = (now - LOOKBACK).date().isoformat()
        # settlement dates are UK dates, which run ahead of UTC late at night in summer
        date_to = (now + timedelta(hours=1)).date().isoformat()
        r = requests.get(
            'https://data.elexon.co.uk/bmrs/api/v1/datasets/FUELHH',
            params={'settlementDateFrom': date_from, 'settlementDateTo': date_to, 'format': 'json'},
            timeout=30,
        )
        r.raise_for_status()
        data = r.json()
        rows = data if isinstance(data, list) else data.get('data', [])
        count = 0
        for row in rows:
            con.execute(
                "insert into bronze.raw_generation"
                "(settlement_date, settlement_period, fuel_type, generation, start_time, loaded_at)"
                " values (?,?,?,?,?,current_timestamp)",
                [row['settlementDate'], row['settlementPeriod'], row['fuelType'],
                 str(row['generation']), row['startTime']]
            )
            count += 1
        results['generation'] = f"OK — {count} rows"
    except Exception as e:
        results['generation'] = f"ERROR — {e}"

    # Open-Meteo — hourly weather for Birmingham
    try:
        r = requests.get(
            'https://api.open-meteo.com/v1/forecast',
            params={
                'latitude': LATITUDE,
                'longitude': LONGITUDE,
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
                "insert into bronze.raw_weather"
                "(time,temperature_2m,windspeed_10m,cloudcover,direct_radiation,wind_direction_10m,precipitation,loaded_at)"
                " values (?,?,?,?,?,?,?,current_timestamp)",
                [t, temp, wind, cld, rad, wdir, precip]
            )
        results['weather'] = f"OK — {len(rows)} rows"
    except Exception as e:
        results['weather'] = f"ERROR — {e}"

    # Carbon Intensity API — regional
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

    # Octopus Agile prices, last 24h plus everything published ahead (up to 48h)
    try:
        r = requests.get(
            'https://api.octopus.energy/v1/products/',
            params={'is_variable': 'true', 'page_size': 100},
            timeout=15,
        )
        r.raise_for_status()
        agile_products = [
            p for p in r.json().get('results', [])
            if 'AGILE' in p['code']
            and p.get('direction', 'IMPORT') == 'IMPORT'
            and not p.get('is_prepay', False)
        ]
        if not agile_products:
            raise ValueError("No Agile product found")
        product_code = sorted(agile_products, key=lambda p: p['code'], reverse=True)[0]['code']
        tariff_code = f"E-1R-{product_code}-{AGILE_REGION}"

        now = datetime.now(timezone.utc)
        period_from = (now - LOOKBACK).strftime('%Y-%m-%dT%H:%M:%SZ')
        period_to   = (now + timedelta(hours=48)).strftime('%Y-%m-%dT%H:%M:%SZ')
        r = requests.get(
            f'https://api.octopus.energy/v1/products/{product_code}/electricity-tariffs/{tariff_code}/standard-unit-rates/',
            params={'page_size': 200, 'period_from': period_from, 'period_to': period_to},
            timeout=15,
        )
        r.raise_for_status()
        rates = r.json().get('results', [])
        for rate in rates:
            con.execute(
                "insert into bronze.raw_prices values (?,?,?,?,current_timestamp)",
                [rate['valid_from'], rate['valid_to'], rate['value_inc_vat'], product_code]
            )
        results['prices'] = f"OK — {len(rates)} rates ({product_code})"
    except Exception as e:
        results['prices'] = f"ERROR — {e}"

    # Carbon Intensity API, national: last 24h actuals + 48h forecast
    try:
        now = datetime.now(timezone.utc)
        past = now - LOOKBACK
        future = now + timedelta(hours=48)
        url = (
            f"https://api.carbonintensity.org.uk/intensity/"
            f"{past.strftime('%Y-%m-%dT%H:%MZ')}/"
            f"{future.strftime('%Y-%m-%dT%H:%MZ')}"
        )
        r = requests.get(url, headers={'Accept': 'application/json'}, timeout=15)
        r.raise_for_status()
        rows = r.json().get('data', [])
        count = 0
        for row in rows:
            intensity = row.get('intensity', {})
            con.execute(
                "insert into bronze.raw_carbon_national values (?,?,?,?,?,current_timestamp)",
                [
                    row['from'], row['to'],
                    str(intensity.get('actual') or ''),
                    str(intensity.get('forecast') or ''),
                    str(intensity.get('index') or ''),
                ]
            )
            count += 1
        results['carbon_national'] = f"OK — {count} rows"
    except Exception as e:
        results['carbon_national'] = f"ERROR — {e}"

    return results


if __name__ == '__main__':
    main()
