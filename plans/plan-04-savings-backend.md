# Plan 4: Savings Tracker Backend

**Objective**: Add endpoints so logged-in users can log appliance sessions and retrieve money/carbon saved compared to the daily average price.
**Requires**: Plan 1 complete (auth tables and `get_current_user` must exist).
**Touches**: `dashboard/app.py`, `tests/test_api.py`

---

## Context

Auth from Plan 1 is in place. This plan adds `app.usage_log` and four endpoints.
The savings calculation compares actual price paid (looked up from `main_gold.mart_price_carbon`)
against the daily average price for that day. This is intentionally conservative
(daily avg, not peak) so the numbers are honest. Use `query()` for all reads —
it is already used by all existing endpoints in `dashboard/app.py`.

## What to build

### 1. DuckDB schema

```sql
CREATE TABLE IF NOT EXISTS app.usage_log (
    id            VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id       VARCHAR NOT NULL REFERENCES app.users(id),
    device_name   VARCHAR NOT NULL,
    start_time    TIMESTAMP NOT NULL,
    duration_h    DOUBLE NOT NULL,
    kw_rating     DOUBLE NOT NULL,
    kwh           DOUBLE NOT NULL,         -- computed: duration_h * kw_rating
    cost_actual   DOUBLE,                  -- £, computed from avg price in window
    cost_optimal  DOUBLE,                  -- £, computed from daily avg price
    saving        DOUBLE,                  -- £, cost_optimal - cost_actual
    logged_at     TIMESTAMP DEFAULT now()
);
```

### 2. Savings calculation logic

When a session is logged, compute cost on the backend:

```python
# 1. kwh
kwh = duration_h * kw_rating

# 2. Fetch avg price for the actual window
#    (start_time to start_time + duration_h hours)
window_price_rows = query("""
    SELECT AVG(price_p_kwh) AS avg_price
    FROM main_gold.mart_price_carbon
    WHERE period_utc >= ?
      AND period_utc < ?
""", [start_time, start_time + timedelta(hours=duration_h)])
avg_price_p = window_price_rows[0]['avg_price']   # pence/kWh

# 3. Fetch daily avg price for the calendar day of start_time
daily_avg_rows = query("""
    SELECT AVG(price_p_kwh) AS avg_price
    FROM main_gold.mart_price_carbon
    WHERE DATE(period_utc) = DATE(?)
""", [start_time])
daily_avg_p = daily_avg_rows[0]['avg_price']

# 4. Calculate costs
cost_actual  = (avg_price_p or 0)  * kwh / 100   # £
cost_optimal = (daily_avg_p or 0)  * kwh / 100   # £
saving       = cost_optimal - cost_actual          # £, positive = saved
```

If price data is missing for the window, store `None` for the computed fields
(do not crash — partial data is acceptable).

### 3. Endpoints

**POST /api/savings**
- Requires auth
- Body:
  ```json
  {
    "device_name": "EV charge",
    "start_time": "2026-06-08T02:00:00",
    "duration_h": 7.0,
    "kw_rating": 7.4
  }
  ```
- Validate: `duration_h > 0`, `kw_rating > 0`, `device_name` non-empty
- Run savings calculation (above)
- Insert row into `app.usage_log`
- Return the full row including computed `kwh`, `cost_actual`, `cost_optimal`, `saving`, `id`

**GET /api/savings**
- Requires auth
- Return last 50 sessions for the current user, ordered `logged_at DESC`
- Response: list of usage log rows

**DELETE /api/savings/{session_id}**
- Requires auth
- Verify the row belongs to the current user; 403 if not, 404 if not found
- Delete row; return `{"ok": true}`

**GET /api/savings/summary**
- Requires auth
- Return:
  ```json
  {
    "total_saving": 413.80,
    "week_saving": 22.10,
    "month_saving": 66.89,
    "total_sessions": 94,
    "total_kwh": 1842.0
  }
  ```
- Queries:
  ```sql
  SELECT
    SUM(saving)                          AS total_saving,
    SUM(CASE WHEN logged_at >= now() - INTERVAL 7 DAYS  THEN saving END) AS week_saving,
    SUM(CASE WHEN logged_at >= now() - INTERVAL 30 DAYS THEN saving END) AS month_saving,
    COUNT(*)                             AS total_sessions,
    SUM(kwh)                             AS total_kwh
  FROM app.usage_log
  WHERE user_id = ?
  ```
- If no sessions exist, return all zeros (not nulls)

## Implementation notes

- Import `datetime.timedelta` for the window calculation.
- `start_time` arrives as an ISO8601 string from the client — parse with
  `datetime.fromisoformat(start_time)` before using in queries.
- The `query()` function accepts a second positional arg for parameters — check the
  existing implementation in `app.py` for the exact signature.
- Route ordering matters: register `GET /api/savings/summary` before
  `DELETE /api/savings/{session_id}` to avoid `summary` matching as a session_id.

## Tests / verification

Add to `tests/test_api.py`:

1. **test_log_session_returns_computed_fields** — monkeypatch `query` to return
   `avg_price=10.0` for window and `avg_price=20.0` for daily avg; POST a 7h 7.4kW
   session; assert `kwh == 51.8`, `cost_actual ≈ 5.18`, `saving > 0`.

2. **test_log_session_missing_price_data** — monkeypatch `query` to return `None`
   for avg_price; POST session; assert 200 and `saving` is `null` (not a crash).

3. **test_list_savings_empty** — monkeypatch empty query result; GET `/api/savings`;
   assert `[]`.

4. **test_savings_summary_zeros_if_no_data** — monkeypatch to return all nulls;
   GET `/api/savings/summary`; assert all values are 0 (not null).

5. **test_delete_savings_wrong_user_is_403** — monkeypatch row owned by different
   user_id; DELETE; assert 403.

Run: `pytest tests/test_api.py -v`

---
Done when: POST a session with `{"device_name":"EV charge","start_time":"2026-06-08T02:00:00","duration_h":7,"kw_rating":7.4}`, GET `/api/savings/summary`, and see `total_sessions: 1` with a non-zero `total_saving` (or `null` saving if no price data exists for that window, which is also acceptable).
