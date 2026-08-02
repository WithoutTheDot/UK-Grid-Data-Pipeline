# Plan 1: User Authentication Backend

**Objective**: Add email/password user accounts with Bearer token auth to the FastAPI backend.
**Requires**: Nothing.
**Touches**: `dashboard/app.py`, `requirements.txt`, `tests/test_api.py`

---

## Context

The FastAPI backend lives in `dashboard/app.py` and uses a single DuckDB file at
`$ENERGY_DB_PATH` (default `./energy.duckdb`). There is no auth at all right now.
The existing `query()` function opens a read-only DuckDB connection per call — do not
replace it with a shared connection (writer lock conflict with the ingest cron).
A separate write helper is needed for DDL and user data.

The mobile app will send `Authorization: Bearer <token>` headers — no cookies.

## What to build

### 1. DuckDB schema

Run these DDL statements at app startup (in a `startup_event` or `lifespan` handler).
Use `CREATE TABLE IF NOT EXISTS` to be idempotent.

```sql
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.users (
    id        VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    email     VARCHAR NOT NULL UNIQUE,
    pw_hash   VARCHAR NOT NULL,
    created_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.user_sessions (
    token      VARCHAR PRIMARY KEY,
    user_id    VARCHAR NOT NULL REFERENCES app.users(id),
    expires_at TIMESTAMP NOT NULL
);

CREATE TABLE IF NOT EXISTS app.login_attempts (
    ip         VARCHAR NOT NULL,
    attempted_at TIMESTAMP DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app.password_resets (
    token      VARCHAR PRIMARY KEY,
    user_id    VARCHAR NOT NULL REFERENCES app.users(id),
    expires_at TIMESTAMP NOT NULL,
    used       BOOLEAN NOT NULL DEFAULT false
);
```

Also run this cleanup at startup to prevent stale session and rate-limit row accumulation:
```sql
DELETE FROM app.user_sessions WHERE expires_at < now();
DELETE FROM app.login_attempts WHERE attempted_at < now() - INTERVAL 1 HOUR;
```

Write a `write_db(sql, params)` helper that opens DuckDB in **read-write** mode
(not read-only) to perform inserts/updates/deletes. Keep `query()` for all
read-only endpoints — do not touch it.

**Write contention handling**: DuckDB allows only one writer at a time. The alert
checker background task (Plan 3b) also calls `write_db()`. Wrap `write_db` with a
retry loop to handle lock contention from the ingest cron:

```python
import time, duckdb

def write_db(sql: str, params: list = None, retries: int = 3):
    for attempt in range(retries):
        try:
            con = duckdb.connect(DB_PATH, read_only=False)
            con.execute(sql, params or [])
            con.close()
            return
        except duckdb.IOException as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)   # 1s, 2s, 4s backoff
```

### 2. Auth dependency

```python
async def get_current_user(authorization: str = Header(None)) -> dict:
    """FastAPI Depends() — returns {id, email} or raises HTTP 401."""
```

Reads the `Authorization: Bearer <token>` header, looks up the token in
`app.user_sessions` (must not be expired), returns the user row.
Raise `HTTPException(status_code=401, detail="Unauthorized")` on any failure.

### 3. Endpoints

All three endpoints return JSON. No HTML responses.

**POST /auth/signup**
- Body: `{"email": "...", "password": "..."}`
- **Rate limit**: same IP check as login — 10 attempts per 15 minutes, raise 429
- Validate: email not already in `app.users`, password >= 8 chars
- Hash password with `passlib.hash.bcrypt.hash(password)`
- Insert into `app.users`
- Generate a 32-byte hex token via `secrets.token_hex(32)`
- Insert into `app.user_sessions` with `expires_at = now + 30 days`
- Return: `{"token": "<hex>", "email": "<email>", "id": "<uuid>"}`
- Error 409 if email already exists

**POST /auth/login**
- Body: `{"email": "...", "password": "..."}`
- **Rate limit**: check `app.login_attempts` for the request IP (use
  `request.client.host` via FastAPI `Request`). If >= 10 rows in the last 15 minutes,
  raise 429: `{"detail":"Too many attempts. Try again later."}`. Otherwise insert a
  row into `app.login_attempts` before attempting the password check.
- Look up user by email; raise 401 if not found
- `passlib.hash.bcrypt.verify(password, stored_hash)` — raise 401 on mismatch
- Generate new token, insert session, return same shape as signup

**POST /auth/logout**
- Requires auth (`Depends(get_current_user)`)
- Delete the session row for the current token
- Return: `{"ok": true}`

**GET /api/me**
- Requires auth
- Return: `{"authenticated": true, "email": "...", "id": "..."}`

**DELETE /auth/account**
- Requires auth
- Hard delete all user data in order (foreign key safe):
  ```sql
  DELETE FROM app.push_tokens   WHERE user_id = ?;
  DELETE FROM app.user_alerts   WHERE user_id = ?;
  DELETE FROM app.usage_log     WHERE user_id = ?;
  DELETE FROM app.user_settings WHERE user_id = ?;
  DELETE FROM app.user_sessions WHERE user_id = ?;
  DELETE FROM app.users         WHERE id = ?;
  ```
- Return: `{"ok": true}`
- Note: tables from Plans 3a and 4 (push_tokens, user_alerts, usage_log,
  user_settings) must be referenced here. If those plans haven't run yet, omit
  those DELETE lines and add them incrementally as each plan is implemented.

**POST /auth/forgot-password**
- Body: `{"email": "..."}`
- Always return 200 regardless of whether the email exists (prevents user enumeration)
- If `SMTP_HOST` env var is not set, return 200 with `{"ok":true,"note":"email not configured"}`
- If the email exists in `app.users`:
  - Generate a 32-byte hex reset token via `secrets.token_hex(32)`
  - Insert into `app.password_resets` (created at startup — see DDL above) with `expires_at = now + 1 hour`
  - Send email via smtplib (same pattern as alert emails in Plan 3b):
    Subject: `"Leccy: Reset your password"`
    Body: `"Click the link to reset your password:\nhttps://yourdomain.com/reset?token=<token>\n\nThis link expires in 1 hour."`
- Return: `{"ok": true}`

**POST /auth/reset-password**
- Body: `{"token": "...", "new_password": "..."}`
- Look up token in `app.password_resets` — raise 400 if not found, expired, or `used=true`
- Validate `new_password` >= 8 chars
- Update `app.users SET pw_hash = ?`
- Mark `app.password_resets SET used = true`
- **Invalidate all existing sessions**: `DELETE FROM app.user_sessions WHERE user_id = ?`
  — ensures an attacker who had a stolen session cannot remain logged in after the victim resets their password
- Return: `{"ok": true}`

### 4. Dependency

Add to `requirements.txt`:
```
passlib[bcrypt]==1.7.4
```

## Implementation notes

- **Session token security**: tokens are stored as plain VARCHAR in `app.user_sessions`. If the
  DuckDB file is ever exposed, all active sessions are immediately usable. For v1 this is
  acceptable given the Oracle VM threat model, but note the risk. A hardening step would be to
  store `hashlib.sha256(token.encode()).hexdigest()` in the DB and hash the incoming Bearer token
  before lookup — the raw token is only ever in memory and HTTP headers.
- Place all auth routes before the existing API routes in `app.py`.
- The `write_db` helper should use `duckdb.connect(db_path, read_only=False)` —
  the path is already available as a module-level constant in the existing code.
- Token generation: `import secrets; secrets.token_hex(32)` — no JWT, no library.
- Do not add CORS headers — the mobile app talks to the same origin.
- `gen_random_uuid()` is a DuckDB built-in; no extension needed.
- DuckDB schema `app` is separate from `main_bronze`, `main_silver`, `main_gold` —
  no conflict with dbt models.

## Tests / verification

Add to `tests/test_api.py`, following the existing monkeypatch pattern:

1. **test_signup_returns_token** — monkeypatch `write_db` and `query` so they don't
   touch real DB; POST `/auth/signup` with valid email/password; assert response has
   `token` and `email` fields, status 200.

2. **test_signup_duplicate_email_is_409** — second signup with same email returns 409.

3. **test_login_bad_password_is_401** — login with wrong password returns 401.

4. **test_me_without_token_is_401** — GET `/api/me` with no header returns 401.

5. **test_me_with_valid_token** — monkeypatch session lookup to return a fake user;
   GET `/api/me` with `Authorization: Bearer faketoken` returns `{authenticated: true}`.

6. **test_login_rate_limited** — monkeypatch `app.login_attempts` query to return 10
   rows in the last 15 minutes; POST `/auth/login`; assert 429.

7. **test_delete_account_removes_all_rows** — monkeypatch `write_db`; call
   `DELETE /auth/account` with valid auth; assert `write_db` called with DELETE
   statements covering `app.users`, `app.user_sessions`.

8. **test_forgot_password_always_200** — POST `/auth/forgot-password` with unknown
   email; assert 200 (not 404).

9. **test_reset_password_expired_token_is_400** — monkeypatch reset token query to
   return expired row; POST `/auth/reset-password`; assert 400.

Run: `pytest tests/test_api.py -v`

---
Done when: `POST /auth/signup` with `{"email":"test@test.com","password":"password123"}` returns a JSON body containing a `token` field, and `GET /api/me` with `Authorization: Bearer <that_token>` returns `{"authenticated":true,"email":"test@test.com"}`.
