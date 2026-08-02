# Plan 3b: Alert Checker Background Loop

**Objective**: Implement the background task that checks all enabled alerts every 30 minutes and fires notifications via Expo push, Home Assistant webhook, and/or email — with delivery-aware `last_fired_at`, a health log, and an inbound webhook endpoint for HA-triggered checks.
**Requires**: Plan 3a complete (alerts table, push_tokens table, CRUD endpoints, stubs must exist).
**Touches**: `dashboard/app.py`, `requirements.txt`, `tests/test_api.py`

---

## Context

Plan 3a created the tables, CRUD endpoints, and two stubs: `_check_alerts()` returning
`{"checked":0,"fired":0}` and `_checker_health()` returning `{"last_run":null}`. This
plan replaces both stubs with real implementations.

**Three delivery channels, in priority order:**
1. **Expo push notification** — works for all users with the app installed, no extra setup required
2. **Home Assistant webhook** — optional, for HA users who want automation triggers
3. **Email via SMTP** — optional fallback, requires server-side env vars

`last_fired_at` is only updated if at least one delivery channel succeeded. If all
channels fail, the alert will retry on the next 30-minute cycle.

**No emojis** in push notification titles, bodies, webhook payloads, or email text.

## What to build

### 1. New DuckDB table: `app.alert_checker_log`

Add to the startup DDL:

```sql
CREATE TABLE IF NOT EXISTS app.alert_checker_log (
    id          VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    run_at      TIMESTAMP DEFAULT now(),
    checked     INTEGER NOT NULL DEFAULT 0,
    fired       INTEGER NOT NULL DEFAULT 0,
    errors      VARCHAR,   -- JSON array of error strings, nullable
    duration_ms INTEGER
);
```

This table is the paper trail. `GET /api/alerts/health` reads from it so there is
always observable evidence that the checker is running.

### 2. Replace `_check_alerts()` stub

`_check_alerts` is a **synchronous** function — it uses the sync `query()` and
`write_db()` helpers. The lifespan loop calls it via `run_in_executor` to avoid
blocking the event loop. Do not use `async def` here and do not call `asyncio.run()`
inside an already-running loop (that raises `RuntimeError`).

```python
import time
import json
import httpx
import smtplib
from email.message import EmailMessage
from datetime import datetime, timedelta, timezone

EXPO_PUSH_URL = 'https://exp.host/--/api/v2/push/send'

def _check_alerts() -> dict:   # SYNC — called via run_in_executor
    start = time.monotonic()
    errors = []
    checked = 0
    fired = 0

    # 1. Fetch current grid state with freshness check
    price_rows = query("""
        SELECT AVG(price_p_kwh) AS price, AVG(carbon_intensity) AS carbon,
               MAX(period_utc) AS latest_period
        FROM main_gold.mart_price_carbon
        WHERE period_utc >= now() - INTERVAL 30 MINUTES
          AND period_utc <= now()
    """)
    score_rows = query("""
        SELECT MAX(score) AS best_score FROM main_gold.mart_best_windows
        WHERE window_start >= now()
    """)

    # Abort if data is stale (pipeline likely failed)
    if price_rows and price_rows[0]['latest_period']:
        latest = price_rows[0]['latest_period']
        if isinstance(latest, str):
            latest = datetime.fromisoformat(latest).replace(tzinfo=timezone.utc)
        if (datetime.now(timezone.utc) - latest) > timedelta(hours=2):
            write_db(
                "INSERT INTO app.alert_checker_log (checked, fired, errors) VALUES (0, 0, ?)",
                [json.dumps(["Skipped: price data is stale (> 2h old). Pipeline may have failed."])]
            )
            return {'checked': 0, 'fired': 0}

    current_price  = price_rows[0]['price']  if price_rows else None
    current_carbon = price_rows[0]['carbon'] if price_rows else None
    best_score     = score_rows[0]['best_score'] if score_rows else None

    # 2. Fetch all enabled alerts with user contact info and push tokens
    alerts = query("""
        SELECT
            a.*,
            s.ha_webhook_url,
            u.email,
            LIST(p.token) AS push_tokens
        FROM app.user_alerts a
        JOIN app.users u ON u.id = a.user_id
        LEFT JOIN app.user_settings s ON s.user_id = a.user_id
        LEFT JOIN app.push_tokens p ON p.user_id = a.user_id
        WHERE a.enabled = true
        GROUP BY a.id, a.user_id, a.alert_type, a.threshold, a.label,
                 a.enabled, a.last_fired_at, a.quiet_from, a.quiet_to,
                 a.created_at, s.ha_webhook_url, u.email
    """)

    now_utc = datetime.now(timezone.utc)
    now_hhmm = now_utc.strftime('%H:%M')

    for alert in alerts:
        checked += 1

        # 3. Evaluate condition
        condition_met = False
        current_value = None
        if alert['alert_type'] == 'price_below' and current_price is not None:
            condition_met = current_price < alert['threshold']
            current_value = current_price
        elif alert['alert_type'] == 'carbon_below' and current_carbon is not None:
            condition_met = current_carbon < alert['threshold']
            current_value = current_carbon
        elif alert['alert_type'] == 'good_window' and best_score is not None:
            condition_met = best_score > alert['threshold']
            current_value = best_score

        if not condition_met:
            continue

        # 4. Cooldown check (2 hours)
        if alert['last_fired_at']:
            last = alert['last_fired_at']
            if isinstance(last, str):
                last = datetime.fromisoformat(last).replace(tzinfo=timezone.utc)
            if (now_utc - last) < timedelta(hours=2):
                continue

        # 5. Quiet hours check
        if alert['quiet_from'] and alert['quiet_to']:
            if _in_quiet_hours(now_hhmm, alert['quiet_from'], alert['quiet_to']):
                continue

        # 6. Fire all delivery channels; track which succeeded
        delivered = False

        # 6a. Expo push notifications
        push_tokens = list(alert.get('push_tokens') or [])   # DuckDB LIST → Python list
        push_tokens = [t for t in push_tokens if t]          # drop nulls
        if push_tokens:
            messages = [
                {
                    'to': token,
                    'title': _alert_title(alert),
                    'body': _alert_body(alert, current_value),
                    'data': {'alert_id': alert['id'], 'alert_type': alert['alert_type']},
                }
                for token in push_tokens
            ]
            try:
                resp = httpx.post(EXPO_PUSH_URL, json=messages, timeout=10)
                resp.raise_for_status()
                result_data = resp.json().get('data', [])
                # Clean up any tokens Expo reports as invalid (device uninstalled app)
                dead_tokens = [
                    messages[i]['to']
                    for i, r in enumerate(result_data)
                    if isinstance(r, dict) and r.get('details', {}).get('error') == 'DeviceNotRegistered'
                ]
                for dead in dead_tokens:
                    try:
                        write_db("DELETE FROM app.push_tokens WHERE token = ?", [dead])
                    except Exception:
                        pass
                # Delivery succeeded if at least one ticket has status 'ok'
                if any(
                    isinstance(r, dict) and r.get('status') == 'ok'
                    for r in result_data
                ):
                    delivered = True
            except Exception as e:
                errors.append(f"Expo push failed for alert {alert['id']}: {e}")

        # 6b. HA webhook
        if alert.get('ha_webhook_url'):
            try:
                payload = {
                    'source': 'leccy',
                    'alert_type': alert['alert_type'],
                    'threshold': alert['threshold'],
                    'current_value': current_value,
                    'label': alert.get('label'),
                }
                httpx.post(alert['ha_webhook_url'], json=payload, timeout=5)
                delivered = True
            except Exception as e:
                errors.append(f"Webhook failed for alert {alert['id']}: {e}")

        # 6c. Email
        smtp_host = os.getenv('SMTP_HOST')
        if smtp_host and alert.get('email'):
            try:
                _send_alert_email(alert, current_value)
                delivered = True
            except Exception as e:
                errors.append(f"Email failed for alert {alert['id']}: {e}")

        # 7. Only mark fired if at least one channel delivered
        if delivered:
            write_db(
                "UPDATE app.user_alerts SET last_fired_at = now() WHERE id = ?",
                [alert['id']]
            )
            fired += 1

    # 8. Write to checker log
    duration_ms = int((time.monotonic() - start) * 1000)
    write_db(
        """INSERT INTO app.alert_checker_log (checked, fired, errors, duration_ms)
           VALUES (?, ?, ?, ?)""",
        [checked, fired, json.dumps(errors) if errors else None, duration_ms]
    )

    return {'checked': checked, 'fired': fired}
```

### 3. Helper functions

```python
def _in_quiet_hours(now_hhmm: str, quiet_from: str, quiet_to: str) -> bool:
    """Return True if now_hhmm falls within the quiet window.
    Handles overnight spans (e.g. 22:00 to 06:00)."""
    if quiet_from <= quiet_to:
        return quiet_from <= now_hhmm < quiet_to
    else:  # wraps midnight
        return now_hhmm >= quiet_from or now_hhmm < quiet_to

def _alert_title(alert: dict) -> str:
    label = alert.get('label')
    if label:
        return f"Leccy: {label}"
    mapping = {
        'price_below':  'Low price now',
        'carbon_below': 'Low carbon now',
        'good_window':  'Good charging window',
    }
    return f"Leccy: {mapping.get(alert['alert_type'], 'Alert')}"

def _alert_body(alert: dict, current_value) -> str:
    t = alert['alert_type']
    v = f"{current_value:.1f}" if current_value is not None else "unknown"
    if t == 'price_below':
        return f"Price is {v}p/kWh (threshold {alert['threshold']}p)"
    if t == 'carbon_below':
        return f"Carbon is {v} gCO2/kWh (threshold {alert['threshold']}g)"
    if t == 'good_window':
        return f"Score {v} (threshold {alert['threshold']})"
    return "Condition met"

def _send_alert_email(alert: dict, current_value) -> None:
    msg = EmailMessage()
    msg['Subject'] = _alert_title(alert)
    msg['From']    = os.getenv('SMTP_USER')
    msg['To']      = alert['email']
    msg.set_content(
        f"{_alert_title(alert)}\n\n"
        f"{_alert_body(alert, current_value)}\n\n"
        f"This alert will not fire again for 2 hours.\n"
    )
    port = int(os.getenv('SMTP_PORT', '587'))
    with smtplib.SMTP(os.getenv('SMTP_HOST'), port) as s:
        s.starttls()
        s.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASS'))
        s.send_message(msg)
```

### 4. Replace `_checker_health()` stub

```python
def _checker_health() -> dict:
    rows = query("""
        SELECT run_at, checked, fired, errors, duration_ms
        FROM app.alert_checker_log
        ORDER BY run_at DESC
        LIMIT 1
    """)
    if not rows:
        return {'last_run': None, 'status': 'no runs recorded'}
    row = rows[0]
    return {
        'last_run':    row['run_at'].isoformat() if row['run_at'] else None,
        'checked':     row['checked'],
        'fired':       row['fired'],
        'errors':      json.loads(row['errors']) if row['errors'] else [],
        'duration_ms': row['duration_ms'],
        'status':      'ok' if not row['errors'] else 'errors',
    }
```

Wire into the existing `GET /api/alerts/health` endpoint stub.

### 5. Background lifespan loop

`_check_alerts` is sync (uses sync `query()`/`write_db()`). Run it in a thread via
`run_in_executor` — never call `asyncio.run()` inside an already-running event loop.

```python
from contextlib import asynccontextmanager
import asyncio

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_alert_checker_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

async def _alert_checker_loop():
    await asyncio.sleep(60)   # let the app finish starting before first run
    loop = asyncio.get_event_loop()
    while True:
        try:
            # Run sync _check_alerts in a thread — do NOT use asyncio.run() here
            await loop.run_in_executor(None, _check_alerts)
        except Exception as e:
            try:
                write_db(
                    "INSERT INTO app.alert_checker_log (checked, fired, errors) VALUES (0, 0, ?)",
                    [json.dumps([str(e)])]
                )
            except Exception:
                pass
        await asyncio.sleep(30 * 60)
```

Pass `lifespan=lifespan` to `FastAPI()`.

### 6. Inbound webhook endpoint (HA → Leccy)

This allows a Home Assistant automation to trigger an on-demand check — useful when
a HA event fires (e.g. "EV plugged in") and the user wants an immediate best-window
response rather than waiting up to 30 minutes.

**POST /api/webhooks/check**
- No auth (the endpoint is intentionally public — rate-limited by HA, not the internet)
- Rate-limit: check `app.alert_checker_log` — if last run was < 5 minutes ago, return
  cached result rather than re-running: `{"cached": true, "checked": N, "fired": N}`
- Otherwise run `_check_alerts()` and return the result
- Response: `{"cached": false, "checked": N, "fired": N}`

```python
@app.post('/api/webhooks/check')
async def inbound_webhook_check():
    # Rate-limit: don't run if last check was < 5 minutes ago
    recent = query("""
        SELECT checked, fired FROM app.alert_checker_log
        WHERE run_at >= now() - INTERVAL 5 MINUTES
        ORDER BY run_at DESC LIMIT 1
    """)
    if recent:
        return {'cached': True, 'checked': recent[0]['checked'], 'fired': recent[0]['fired']}
    # _check_alerts is sync — run it in a thread via executor.
    # DO NOT use asyncio.run() here; FastAPI routes already run inside the event loop
    # and asyncio.run() raises RuntimeError: "This event loop is already running."
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _check_alerts)
    return {'cached': False, **result}
```

Add a note in the Settings screen (Plan 6g) that the inbound webhook URL is
`POST https://yourdomain.com/api/webhooks/check` — HA users can call this from an
automation when the car is plugged in.

### 7. Environment variables

```
SMTP_HOST     — e.g. smtp.gmail.com  (omit to disable email)
SMTP_PORT     — default 587
SMTP_USER     — sender address
SMTP_PASS     — Gmail app password (not login password)
```

Expo push requires no environment variables — it uses the public Expo push API.

### 8. Dependency

`httpx` already in `requirements.txt` from Plan 2. No new dependencies.

## Implementation notes

- `LIST(p.token)` is a DuckDB aggregate — it returns a list of all push tokens for
  the user. If the user has no registered device, the list is empty (not null).
- `_check_alerts` is sync because it uses sync `query()` / `write_db()`. Both the lifespan
  loop and the inbound webhook route call it via `loop.run_in_executor(None, _check_alerts)`.
  Never use `asyncio.run()` inside FastAPI route handlers or the lifespan loop — the event
  loop is already running and `asyncio.run()` raises `RuntimeError: This event loop is already running`.
- Expo push API accepts a batch of up to 100 messages per request — one request per
  alert check cycle is sufficient for this scale.
- The inbound webhook has no secret/HMAC verification. This is acceptable for v1 since
  a call to this endpoint only triggers a read + conditional notification — it cannot
  write data or access user information.

## Tests / verification

Add to `tests/test_api.py`:

1. **test_check_alerts_price_below_fires** — monkeypatch `query` for price rows
   (price=8.0), alerts query (price_below threshold=12, last_fired_at=null,
   push_tokens=["ExponentPushToken[abc]"], ha_webhook_url=null, email=null);
   monkeypatch `httpx.post`; POST `/api/alerts/check`; assert `fired==1` and
   `httpx.post` called with `EXPO_PUSH_URL`.

2. **test_check_alerts_only_updates_last_fired_on_success** — same setup but
   monkeypatch `httpx.post` to raise `httpx.ConnectError`; assert `fired==0` and
   `write_db` NOT called with `UPDATE ... last_fired_at`.

3. **test_check_alerts_cooldown_suppresses** — same setup but `last_fired_at` is
   1 hour ago; assert `fired==0`.

4. **test_check_alerts_quiet_hours_suppresses** — `quiet_from:"00:00"`,
   `quiet_to:"23:59"`; assert `fired==0`.

5. **test_in_quiet_hours_overnight** — unit test `_in_quiet_hours`:
   `_in_quiet_hours("23:30", "22:00", "06:00")` → True;
   `_in_quiet_hours("12:00", "22:00", "06:00")` → False.

6. **test_health_endpoint_no_runs** — monkeypatch log query to return [];
   GET `/api/alerts/health`; assert `{"last_run":null}`.

7. **test_inbound_webhook_cached** — monkeypatch log query to return a recent row;
   POST `/api/webhooks/check`; assert `{"cached":true}` without running `_check_alerts`.

Run: `pytest tests/test_api.py -v`

Manual integration test:
1. Register a push token via `POST /api/push-token` with a real Expo token from a device
2. Create a price alert with threshold above the current price
3. `POST /api/alerts/check`
4. Confirm push notification arrives on the device within ~10 seconds
5. Check `GET /api/alerts/health` shows `fired: 1`
6. `POST /api/alerts/check` again within 2 hours — confirm `fired: 0` (cooldown)

---
Done when: `POST /api/alerts/check` sends a real Expo push notification to a registered device when the alert condition is met, `last_fired_at` is NOT updated when all delivery channels fail, `GET /api/alerts/health` shows the last run time and result, and `POST /api/webhooks/check` returns a cached result if called within 5 minutes of the last run.
