# Plan 3a: Alerts CRUD Endpoints

**Objective**: Add database tables and REST endpoints so logged-in users can create, list, toggle, and delete alerts, and register their device for push notifications.
**Requires**: Plan 1 complete (auth tables, `write_db`, `get_current_user` must exist).
**Touches**: `dashboard/app.py`, `tests/test_api.py`

---

## Context

Auth infrastructure from Plan 1 is in place. This plan adds the CRUD layer for
alerts plus a push token registration endpoint (needed by Plan 3b to deliver native
push notifications). Every endpoint requires `Depends(get_current_user)` except
`POST /api/push-token` which is also auth-gated. Follow the existing endpoint style
in `dashboard/app.py` — return plain JSON dicts, use `HTTPException` for errors.

## What to build

### 1. DuckDB schema

Run at startup with `CREATE TABLE IF NOT EXISTS`:

```sql
CREATE TABLE IF NOT EXISTS app.user_alerts (
    id            VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id       VARCHAR NOT NULL REFERENCES app.users(id),
    alert_type    VARCHAR NOT NULL,    -- 'price_below' | 'carbon_below' | 'good_window'
    threshold     DOUBLE NOT NULL,
    label         VARCHAR,             -- optional, nullable
    enabled       BOOLEAN NOT NULL DEFAULT true,
    last_fired_at TIMESTAMP,           -- nullable; used for 2h cooldown
    quiet_from    VARCHAR,             -- 'HH:MM', nullable
    quiet_to      VARCHAR,             -- 'HH:MM', nullable
    created_at    TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.push_tokens (
    id         VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    user_id    VARCHAR NOT NULL REFERENCES app.users(id),
    token      VARCHAR NOT NULL UNIQUE,   -- Expo push token e.g. ExponentPushToken[xxx]
    created_at TIMESTAMP DEFAULT now(),
    updated_at TIMESTAMP DEFAULT now()
);
```

### 2. Alert CRUD endpoints

**GET /api/alerts**
- Requires auth
- Return all alerts for the current user, ordered by `created_at DESC`
- Response: `[{"id":"...","alert_type":"price_below","threshold":12.0,"enabled":true,"quiet_from":"22:00","quiet_to":"06:00","last_fired_at":null}, ...]`

**POST /api/alerts**
- Requires auth
- Body:
  ```json
  {
    "alert_type": "price_below",
    "threshold": 12.0,
    "label": "Cheap overnight",
    "quiet_from": "22:00",
    "quiet_to": "06:00"
  }
  ```
- Validate `alert_type` is one of `price_below`, `carbon_below`, `good_window` — raise 422 otherwise
- Validate `threshold > 0`
- `quiet_from` and `quiet_to` optional. If provided, validate `HH:MM` format via `re.match(r'^\d{2}:\d{2}$', value)`
- Insert row; return the created alert object including `id`

**DELETE /api/alerts/{alert_id}**
- Requires auth
- Verify the alert belongs to the current user; raise 404 if not found, 403 if owned by another user
- Delete row; return `{"ok": true}`

**PATCH /api/alerts/{alert_id}/toggle**
- Requires auth
- Flip `enabled`: `SET enabled = NOT enabled`
- Verify ownership same as DELETE
- Return the updated alert object

### 3. Push token registration endpoint

**POST /api/push-token**
- Requires auth
- Body: `{"token": "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]"}`
- Validate token starts with `"ExponentPushToken["` — raise 422 if not
- Upsert into `app.push_tokens`: if a row for this token already exists, update
  `updated_at`; if not, insert. If the user already has a different token registered,
  keep both (a user may have multiple devices).
- Return: `{"ok": true}`

### 4. Manual trigger endpoint stub (for Plan 3b)

**POST /api/alerts/check**
- No auth required (internal / testing)
- Calls `_check_alerts()` — stub to return `{"checked": 0, "fired": 0}` for now
- Plan 3b replaces the stub with the real implementation

**GET /api/alerts/health**
- No auth required
- Calls `_checker_health()` — stub returning `{"last_run": null, "status": "not started"}`
- Plan 3b fills this in

## Implementation notes

- `app.push_tokens` uses `UNIQUE` on `token` — one row per physical device, not per user.
  Multiple users on the same device is not a supported case.
- Route order in `app.py` matters: register `GET /api/alerts/health` and
  `POST /api/alerts/check` before `PATCH /api/alerts/{alert_id}/toggle` and
  `DELETE /api/alerts/{alert_id}` so literal path segments match before wildcards.
- `quiet_from` and `quiet_to` stored as `HH:MM` strings — do not use SQL time types.
- **Edge case**: if both `quiet_from` and `quiet_to` are `"00:00"`, the quiet window covers
  the entire day — the alert will never fire while enabled. This is not a crash but silent
  suppression. Plan 3b's `_in_quiet_hours("XX:XX", "00:00", "00:00")` evaluates as
  `"00:00" <= "00:00"` which is `True`, so the check is already correct; the UI in Plan 6f
  should warn the user if both times are identical ("Alert will never fire with these quiet hours").

## Tests / verification

Add to `tests/test_api.py`:

1. **test_create_alert** — POST `/api/alerts` with valid body; assert 200, response has
   `id` field and `alert_type` matches.

2. **test_create_alert_bad_type_is_422** — POST with `alert_type:"invalid"`; assert 422.

3. **test_list_alerts_empty** — monkeypatch query to return `[]`; GET `/api/alerts`;
   assert response is `[]`.

4. **test_toggle_alert** — monkeypatch query to return alert row with `enabled:true`;
   PATCH toggle; assert response `enabled` is `false`.

5. **test_delete_alert_wrong_user_is_403** — monkeypatch to return alert owned by a
   different `user_id`; DELETE; assert 403.

6. **test_register_push_token** — POST `/api/push-token` with
   `{"token":"ExponentPushToken[abc123]"}`; assert 200 and `{"ok":true}`.

7. **test_register_push_token_invalid_format_is_422** — POST with `{"token":"not-a-token"}`;
   assert 422.

8. **test_alerts_check_stub** — POST `/api/alerts/check`; assert 200 and
   body is `{"checked":0,"fired":0}`.

Run: `pytest tests/test_api.py -v`

---
Done when: A logged-in user can POST to `/api/alerts` to create a `price_below` alert, GET returns it, PATCH toggle flips `enabled`, DELETE removes it, and `POST /api/push-token` with a valid Expo token returns `{"ok":true}` — all passing in pytest.
