# Leccy — Google Play Publishing Checklist

This is a manual process. No Claude Code execution required.
All commands run in the `Leccy/` directory on your development machine.

---

## Pre-flight

- [ ] Backend is live at a public HTTPS URL (Plan 5 complete)
- [ ] Set `LECCY_API_URL` to the production URL (e.g. `https://yourdomain.com`)
      in your build environment before running `eas build`
- [ ] All Phase 6 mobile screens tested in Expo Go
- [ ] `app.json` has correct `android.package` (change `com.leccy.app` to your
      reverse domain if needed) and `android.versionCode: 1`

---

## Step 1 — Google Play Developer account

1. Go to https://play.google.com/console
2. Pay the $25 (~£20) one-time registration fee
3. Complete the account details form
4. Account verification takes 1–3 days — proceed with steps below in the meantime

---

## Step 2 — Assets to prepare

| Asset | Size | Notes |
|-------|------|-------|
| `Leccy/assets/adaptive-icon.png` | 1024x1024 PNG | Foreground on green bg; no rounded corners |
| `Leccy/assets/icon.png` | 1024x1024 PNG | Play Store icon (same as adaptive foreground) |
| `Leccy/assets/splash.png` | 1284x2778 PNG | Cream background, centred wordmark |
| Feature graphic | 1024x500 PNG | Cream bg, wordmark, tagline: "Smart energy, no fuss" |
| Screenshots (2–8) | 320px+ wide | Home screen, Schedule screen, Savings screen |

---

## Step 3 — Install EAS CLI and configure

```bash
npm install -g eas-cli
eas login          # log in with your Expo account (create one at expo.dev if needed)
eas build:configure
```

`eas.json` is already configured in the repo.

---

## Step 4 — Build the signed Android App Bundle

```bash
LECCY_API_URL=https://yourdomain.com eas build --platform android --profile production
```

EAS will:
1. Ask to create a new keystore — say **yes** on the first build
2. Upload code to Expo build servers
3. Build and sign the AAB (~5–10 minutes)
4. Return a download URL when complete

**CRITICAL — back up the keystore after the first build:**
```bash
eas credentials --platform android
# Choose "Download keystore" and store the .jks file outside the repo
```
Losing the keystore means you can never update the app under the same Play listing.

---

## Step 5 — Create the Play Store listing

In https://play.google.com/console:

1. **Create App**: Android, free, confirm policy compliance
2. **App details**:
   - Name: **Leccy**
   - Short description (max 80 chars):
     `See live UK energy prices and grid carbon — find the best time to charge.`
   - Full description: explain Elexon, Carbon Intensity API, Octopus Energy, Open-Meteo
     data sources; target audience: UK EV owners and smart home users on Agile tariffs
3. **Graphics**: upload icon (512x512), feature graphic, screenshots
4. **Category**: Tools
5. **Content rating**: complete questionnaire, answer No to all sensitive content
6. **Target audience**: 18+

---

## Step 6 — Privacy policy

The `/privacy` and `/delete-account` routes are already deployed (Plan 7 backend).
Enter `https://yourdomain.com/privacy` in the Play Console privacy policy URL field.

---

## Step 7 — Data deletion (required since May 2024)

In Play Console under **App content > Data deletion**:
- URL: `https://yourdomain.com/delete-account`
- Confirm: "Users can delete their account and data from within the app"
- Data types deleted: Account info, App activity

In-app deletion: Settings > Delete account calls `DELETE /auth/account`.

---

## Step 8 — Upload the AAB

1. Play Console: **Production > Releases > Create release**
2. Upload the `.aab` downloaded from EAS
3. Release name: `1.0.0`
4. Release notes: `Initial release`
5. Review and submit

---

## Step 9 — Wait for review

- First-time apps: 1–3 days
- Check Play Console for policy violations or missing info

---

## Step 10 — After approval

1. Install from the Play Store on a fresh device (not Expo Go) to confirm it works
2. **For future updates**: increment `versionCode` in `app.json`, run `eas build` again,
   upload the new AAB to a new Play Console release

---

## Short description (copy/paste)

```
See live UK energy prices and grid carbon — find the best time to charge.
```

## Full description (template — customise before submitting)

```
Leccy helps UK EV owners and smart home users find the cheapest, cleanest time
to run their appliances.

Live data, updated every 30 minutes:
- Half-hourly Agile Octopus prices (48h forward)
- National and regional carbon intensity from the Carbon Intensity API
- Generation mix by fuel type from Elexon BMRS

Features:
- Home screen: see the current price, carbon intensity, and renewable percentage at a glance
- Schedule: pick a duration, see the best charge windows today and tomorrow
- Savings: log your appliance runs and see how much you have saved vs a flat 27p/kWh rate
- Alerts: get a push notification when the price drops below your threshold or the grid is clean
- Home Assistant: send alerts to your HA instance via a webhook

Data sources: Elexon BMRS, Carbon Intensity API (carbonintensity.org.uk),
Octopus Energy Agile tariff, Open-Meteo.

No subscription. No ads.
```
