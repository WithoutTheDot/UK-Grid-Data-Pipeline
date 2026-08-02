# Plan 2: User Settings Backend

**Objective**: Add endpoints so logged-in users can save their tariff type, flat rate, and Home Assistant webhook URL, and can change their password.
**Requires**: Plan 1 complete (auth tables and `get_current_user` dependency must exist).
**Touches**: `dashboard/app.py`, `tests/test_api.py`

---

## Context

All auth infrastructure from Plan 1 is in place: `app.users`, `app.user_sessions`,
`write_db()`, and `get_current_user` FastAPI dependency. Follow the existing style:
new endpoints sit in `dashboard/app.py` alongside current routes; every endpoint
that requires auth uses `Depends(get_current_user)`. The `write_db()` helper opens
DuckDB read-write; `query()` stays read-only.

## What to build

### 1. DuckDB schema

Run at startup (idempotent `CREATE TABLE IF NOT EXISTS`):

```sql
CREATE TABLE IF NOT EXISTS app.user_settings (
    user_id        VARCHAR PRIMARY KEY REFERENCES app.users(id),
    tariff_type    VARCHAR NOT NULL DEFAULT 'agile',   -- 'agile' | 'flat'
    flat_rate_p    DOUBLE,                              -- pence/kWh, nullable
    ha_webhook_url VARCHAR,                             -- nullable
    updated_at     TIMESTAMP DEFAULT now()
);
```

### 2. Endpoints

**GET /api/settings**
- Requires auth
- Query `app.user_settings` by `user_id`
- If no row exists yet, return defaults: `{"tariff_type":"agile","flat_rate_p":null,"ha_webhook_url":null}`
- Otherwise return the stored values

**POST /api/settings**
- Requires auth
- Body: `{"tariff_type": "agile"|"flat", "flat_rate_p": <float|null>, "ha_webhook_url": "<url|null>"}`
- Validate: if `tariff_type == "flat"`, `flat_rate_p` must be present and > 0
- Upsert into `app.user_settings` using DuckDB `INSERT OR REPLACE`
- Return: the saved settings object (same shape as GET)

**POST /api/settings/test-webhook**
- Requires auth
- Reads `ha_webhook_url` from `app.user_settings` for the current user
- If not set, return 400: `{"detail":"No webhook URL saved"}`
- **SSRF protection**: before firing, parse the URL and reject any that resolve to private/internal
  IP ranges. Raise 422 if the URL:
  - does not start with `http://` or `https://`
  - has a hostname that is a private IP: `10.x.x.x`, `172.16–31.x.x`, `192.168.x.x`, `169.254.x.x`, `127.x.x.x`
  - Example check: `import ipaddress, urllib.parse; h = urllib.parse.urlparse(url).hostname; ipaddress.ip_address(h)` — catch and allow hostnames (not raw IPs), block raw private IPs.
  - Note: hostname-based URLs (e.g. `homeassistant.local`) are not blocked by this check — that is acceptable for v1.
- Fire a POST request to that URL using `httpx.post(url, json={"source":"leccy","event":"test"}, timeout=5)`
- Return: `{"ok": true, "status_code": <int>}` on success, or 502 if the POST fails/times out
- Add `httpx` to `requirements.txt` if not already present

**GET /api/settings/ha-blueprint**
- No auth required (blueprint is generic — no user data)
- Returns a plain-text YAML Home Assistant blueprint that the user can import directly
  into their HA instance to receive Leccy alerts as mobile notifications
- Response: `Content-Type: text/yaml`
- Blueprint content:

```yaml
blueprint:
  name: Leccy Alert Handler
  description: >
    Receive Leccy energy alerts and send them as a mobile notification.
    Trigger your automations via the Leccy webhook URL or the on-demand
    check endpoint (POST /api/webhooks/check).
  domain: automation
  input:
    notify_device:
      name: Notification target
      description: Device to notify (must have the Home Assistant Companion app)
      selector:
        device:
          integration: mobile_app

trigger:
  - platform: webhook
    webhook_id: leccy_alert

action:
  - service: notify.mobile_app_{{ trigger.data.notify_device | default('') }}
    data:
      title: "Leccy: {{ trigger.json.label | default(trigger.json.alert_type) }}"
      message: >
        {{ trigger.json.alert_type | replace('_', ' ') | title }}
        — current value {{ trigger.json.current_value }}
        (threshold {{ trigger.json.threshold }})
```

The webhook ID `leccy_alert` means the user's HA webhook URL will be:
`http://homeassistant.local:8123/api/webhook/leccy_alert`

Include this URL as a hint in the response body alongside the YAML:
```json
{
  "blueprint_yaml": "...",
  "example_webhook_url": "http://homeassistant.local:8123/api/webhook/leccy_alert",
  "inbound_check_url": "POST https://yourdomain.com/api/webhooks/check"
}
```

**POST /api/auth/change-password**
- Requires auth
- Body: `{"current_password": "...", "new_password": "..."}`
- Verify `current_password` against the stored bcrypt hash in `app.users`; raise 401 if wrong
- Validate `new_password` >= 8 chars; raise 422 if too short
- Hash the new password with `passlib.hash.bcrypt.hash(new_password)`
- Update `app.users` SET `pw_hash = ?` WHERE `id = ?`
- Return: `{"ok": true}`

### 3. Dependency

Add to `requirements.txt` if not present:
```
httpx==0.27.0
```

## Implementation notes

- DuckDB `INSERT OR REPLACE INTO app.user_settings VALUES (...)` handles both
  insert and update in one statement. Include all columns explicitly.
- The webhook test fires a real HTTP request; in tests, monkeypatch `httpx.post`.
- Do not attempt to validate the webhook URL format beyond "it's a non-empty string" —
  let the 502 response tell the user if the URL is wrong.

## Tests / verification

Add to `tests/test_api.py`:

1. **test_get_settings_returns_defaults** — monkeypatch `query` to return empty;
   GET `/api/settings` with valid auth token returns `{"tariff_type":"agile"}`.

2. **test_post_settings_saves** — POST `/api/settings` with tariff_type and webhook;
   assert 200 and the returned object matches what was sent.

3. **test_flat_rate_required_when_tariff_flat** — POST with `tariff_type:"flat"` and
   no `flat_rate_p`; assert 422.

4. **test_test_webhook_no_url_is_400** — monkeypatch settings query to return no URL;
   POST `/api/settings/test-webhook`; assert 400.

5. **test_change_password_wrong_current_is_401** — monkeypatch bcrypt verify to return
   False; POST `/api/auth/change-password`; assert 401.

6. **test_ha_blueprint_returns_yaml** — GET `/api/settings/ha-blueprint` with no auth;
   assert 200, `Content-Type` contains `text/yaml`, response body contains
   `webhook_id: leccy_alert`, and JSON wrapper has `inbound_check_url` key.

Run: `pytest tests/test_api.py -v`

---
Done when: A logged-in user can POST `{"tariff_type":"flat","flat_rate_p":18.5,"ha_webhook_url":"http://homeassistant.local/api/webhook/leccy_alert"}` to `/api/settings`, receive 200, GET `/api/settings` returns the saved values, and GET `/api/settings/ha-blueprint` returns YAML containing `webhook_id: leccy_alert` without requiring auth.
