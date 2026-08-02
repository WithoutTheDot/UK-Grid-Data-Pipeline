# Plan 7: Google Play Publishing

**Objective**: Build a signed Android App Bundle and submit it to the Google Play Store under the "Leccy" listing.
**Requires**: All Phase 6 plans complete. Backend live at a public HTTPS URL (Plan 5). A Google Play Developer account ($25 one-time fee).
**Touches**: `Leccy/eas.json`, `Leccy/app.json`. No application code changes.

---

## Context

This plan is a series of manual steps — no Claude Code execution is needed, and no
application code changes are made. All steps are performed in a terminal on your
development machine (not the Oracle server). EAS Build handles Android signing —
you do not need Android Studio or the Android SDK installed locally.

**Before starting**: make sure `BASE_URL` in `Leccy/src/api/client.ts` points to the
production Oracle Cloud domain (`https://yourdomain.com`), not a local IP.

## What to build

### Step 1 — Google Play Developer account

1. Go to play.google.com/console
2. Pay the $25 (~£20) one-time registration fee.
3. Complete the account details form.
4. Account verification takes 1–3 days; proceed with app preparation in the meantime.

### Step 2 — Update `app.json`

Ensure these fields are set correctly:

```json
{
  "expo": {
    "name": "Leccy",
    "slug": "leccy",
    "version": "1.0.0",
    "orientation": "portrait",
    "android": {
      "package": "com.yourname.leccy",
      "versionCode": 1,
      "adaptiveIcon": {
        "foregroundImage": "./assets/adaptive-icon.png",
        "backgroundColor": "#1E6B3C"
      },
      "permissions": []
    },
    "icon": "./assets/icon.png",
    "splash": {
      "image": "./assets/splash.png",
      "backgroundColor": "#F2EDE6"
    }
  }
}
```

Notes:
- `package` must be globally unique on the Play Store — use reverse domain notation.
- `versionCode` is an integer that must increment with every Play Store upload.
- Icon: 1024x1024 PNG, no transparency. Background: `#1E6B3C` (forest green).
  Foreground: white "L" lettermark or the full "Leccy" wordmark. No rounded corners
  on the source image (Android applies them).
- Splash screen: cream background `#F2EDE6`, wordmark centred.

### Step 3 — Install EAS CLI and configure

```bash
cd Leccy
npm install -g eas-cli
eas login        # log in with your Expo account (create one at expo.dev if needed)
eas build:configure
```

`eas build:configure` creates `eas.json`. Confirm it contains a `production` profile:

```json
{
  "build": {
    "production": {
      "android": {
        "buildType": "app-bundle"
      }
    }
  }
}
```

### Step 4 — Build the signed Android App Bundle

```bash
eas build --platform android --profile production
```

EAS will:
1. Ask if you want to create a new keystore — say yes on the first build.
2. Upload your code to Expo's build servers.
3. Build and sign the AAB.
4. Return a download URL when complete (takes ~5–10 minutes).

**CRITICAL**: After the first build, download and back up the keystore:
```bash
eas credentials --platform android
```
Choose "Download keystore". Store the `.jks` file somewhere safe outside the repo.
Losing the keystore means you can never update the app under the same Play listing.

### Step 5 — Create the Play Store listing

In the Google Play Console (play.google.com/console):

1. Create App: choose Android, free, declare it meets store policies.

2. App details:
   - App name: **Leccy** (exact capitalisation)
   - Short description (max 80 chars): "See live UK energy prices and grid carbon — find the best time to charge."
   - Full description (max 4000 chars): describe what it does, which data sources it uses
     (Elexon, Carbon Intensity API, Octopus Energy, Open-Meteo), who it is for
     (UK EV owners and smart home users on Agile or smart tariffs).
     No emojis in any description text.

3. Graphics:
   - App icon: 512x512 PNG (can be same as `icon.png`)
   - Feature graphic: 1024x500 PNG (a simple branded banner — cream bg, wordmark,
     short tagline like "Smart energy, no fuss")
   - Screenshots: minimum 2, maximum 8. Take them from a real device via Expo Go
     or from the Android emulator. Required size: at least 320px wide. Show the
     Home screen, Schedule screen, and Savings screen.

4. Category: Tools

5. Content rating: complete the questionnaire. Answer "No" to all sensitive content
   questions — this app will receive an "Everyone" rating.

6. Target audience: 18+

### Step 6 — Privacy policy

Google Play requires a privacy policy URL for any app that handles personal data
(email addresses and usage logs qualify).

Host a minimal privacy policy at `https://yourdomain.com/privacy`. Minimum content:

```
Leccy Privacy Policy

We collect your email address and appliance usage logs to provide the savings
tracking feature. This data is stored on our servers and is never sold to third
parties. To delete your account and all associated data, go to Settings >
Delete account in the app, or visit yourdomain.com/delete-account.

Data sources: Elexon BMRS, Carbon Intensity API, Octopus Energy API, Open-Meteo.
These are public APIs; no personal data is sent to them.

Last updated: [date]
```

Add FastAPI routes to serve these pages:
```python
@app.get("/privacy")
def privacy():
    return HTMLResponse(content=open("dashboard/templates/privacy.html").read())

@app.get("/delete-account")
def delete_account_page():
    return HTMLResponse(content=open("dashboard/templates/delete_account.html").read())
```

Create `dashboard/templates/delete_account.html` — a minimal HTML form:
```html
<!DOCTYPE html>
<html>
<head><title>Delete Leccy Account</title></head>
<body style="font-family:sans-serif;max-width:480px;margin:40px auto;padding:0 16px">
  <h2>Delete your Leccy account</h2>
  <p>Enter your email address. We will delete your account and all associated data
     within 30 days and send a confirmation email.</p>
  <form method="POST" action="/delete-account/request">
    <input type="email" name="email" placeholder="your@email.com"
           required style="width:100%;padding:10px;margin-bottom:12px;font-size:16px">
    <button type="submit"
            style="background:#DC2626;color:#fff;border:none;padding:12px 24px;
                   font-size:16px;cursor:pointer;border-radius:6px">
      Request account deletion
    </button>
  </form>
</body>
</html>
```

Add the corresponding POST handler:
```python
@app.post("/delete-account/request")
async def delete_account_request(email: str = Form(...)):
    # Send yourself an email so you can manually process the deletion
    # (or automate it later — this is the minimum Play Store requires)
    smtp_host = os.getenv('SMTP_HOST')
    if smtp_host:
        msg = EmailMessage()
        msg['Subject'] = f'Leccy account deletion request: {email}'
        msg['From'] = os.getenv('SMTP_USER')
        msg['To'] = os.getenv('SMTP_USER')   # send to yourself
        msg.set_content(f'Account deletion requested for: {email}\nProcess via DELETE /auth/account')
        with smtplib.SMTP(smtp_host, int(os.getenv('SMTP_PORT', 587))) as s:
            s.starttls()
            s.login(os.getenv('SMTP_USER'), os.getenv('SMTP_PASS'))
            s.send_message(msg)
    return HTMLResponse('<p>Request received. We will process it within 30 days.</p>')
```

Add `python-multipart` to `requirements.txt` (needed for `Form()` in FastAPI).

### Step 7 — Account deletion — Play Store requirement (enforced May 2024)

Any app that allows account creation must provide both in-app deletion AND a
web-based deletion option. Failure causes rejection.

**In-app**: The "Delete account" row in Settings (Plan 6g) calls `DELETE /auth/account`.

**Web-based**: The `/delete-account` page added in Step 6 satisfies this.

In the Play Console under **App content > Data deletion**:
- Enter URL: `https://yourdomain.com/delete-account`
- Select: "Users can delete their account and data from within the app"
- Confirm which data types are deleted (select: Account info, App activity)

Do this before submitting for review — the Play Console will flag it as missing
if the Data safety section is incomplete.

### Step 7 — Upload the AAB

1. In Play Console: Production > Releases > Create release
2. Upload the `.aab` file downloaded from EAS Build
3. Release name: "1.0.0"
4. Release notes (optional): "Initial release"
5. Review the release — Play Console will warn about any missing assets
6. Submit for review

### Step 8 — Wait for review

First-time apps typically take 1–3 days. Google may ask for clarifications.
Check the Play Console for any policy violations or missing information.

### Step 9 — After approval

1. The app goes live on the Play Store.
2. Install it on a fresh device via the Play Store listing (not Expo Go) to confirm it works.
3. Future updates: increment `versionCode` in `app.json`, run `eas build` again,
   upload the new AAB to a new Play Console release.

## Verification

Final test from a fresh Android device:
1. Open the Play Store, search "Leccy" — the listing appears.
2. Install the app.
3. Open it — the Home screen loads with live grid data.
4. Sign up for an account.
5. Log a session in the Savings tab — saving appears.

---
Done when: The app is searchable on the Google Play Store, installs cleanly on a fresh Android device without Expo Go, and a new account can be created and used to log a savings session.
