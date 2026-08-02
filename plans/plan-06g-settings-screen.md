# Plan 6g: Mobile App — Settings Screen

**Objective**: Build the Settings screen with account management, tariff configuration, Home Assistant webhook, appearance (theme) toggle, and an About section.
**Requires**: Plan 6a (app shell), Plan 6c (AuthContext), Plan 2 (settings endpoints live).
**Touches**: `Leccy/src/screens/SettingsScreen.tsx`

---

## Context

Settings is the last screen. Account rows require login; the Appearance and About
sections are visible to everyone. Each group of settings lives in its own white card
on the cream background — the same card spec used throughout the app. No full-colour
(green bg) card on this screen. Fields that require a server round-trip have an
explicit Save button; radio/toggle selections persist immediately.

**No emojis anywhere** — not in labels, placeholder text, or setting descriptions.

## Visual spec

- Background: `#F2EDE6` (cream)
- Each settings group: white card, `borderRadius:16`, shadow, padding 16
- Section header above each card: plain `Text` in `#9CA3AF`, 11sp, uppercase (not a `SectionLabel` with a divider — these are group titles above the card, not content headers)
- Row inside a card: `flexDirection:'row', alignItems:'center', paddingVertical:12`
- Chevron rows: right-side `Feather` "chevron-right" icon in `#9CA3AF`
- Dividers between rows inside a card: `height:1, backgroundColor:'#E5E7EB'`
- Radio button: use simple circles — `Feather "circle"` (empty) / `Feather "check-circle"` (selected, `#1E6B3C`)
- Save buttons: `backgroundColor:'#1E6B3C', color:'#FFFFFF'`, `borderRadius:8`, padding 10, `fontSize:14`
- "Sign out" row text: `color:'#DC2626'`

## What to build

### 1. `SettingsScreen.tsx` state and data loading

```typescript
const { isLoggedIn, email, logout } = useAuth();
const [settings, setSettings] = useState<UserSettings | null>(null);
const [tariffType, setTariffType] = useState<'agile' | 'flat'>('agile');
const [flatRate, setFlatRate]     = useState<string>('');
const [webhookUrl, setWebhookUrl] = useState<string>('');
const [theme, setTheme]           = useState<'system' | 'light' | 'dark'>('system');
const [saving, setSaving]         = useState(false);
const [webhookStatus, setWebhookStatus] = useState<'idle' | 'testing' | 'ok' | 'fail'>('idle');
```

Load on mount (if logged in): fetch `GET /api/settings` and populate state.

### 2. ACCOUNT card (logged-in only)

```
ACCOUNT

you@example.com          (secondary text, not editable)
─────────────────────────
Change password      >   (chevron row)
─────────────────────────
Sign out                 (red text, no chevron)
```

If `!isLoggedIn`: show instead:
```
ACCOUNT

Sign in to access your account   >  (chevron → navigate to Login modal)
```

**Change password** row → open a `Modal` (slide) with:
- Current password input
- New password input (show/hide toggle)
- Confirm new password input
- "Update password" green button → `POST /api/auth/change-password`
- Show success message or inline error
- Close on success

**Sign out** row → call `auth.logout()` (clears token from secure store).

**Delete account** row (below Sign out, red text, no chevron):
- Tap → show a confirmation `Alert.alert`:
  ```
  Title:   "Delete account"
  Message: "This will permanently delete your account and all saved data.
             This cannot be undone."
  Buttons: [ "Cancel" (dismiss), "Delete" (red, destructive) ]
  ```
- On confirm: call `DELETE /auth/account` then `auth.logout()`
- Show a brief error message if the request fails — do not log out on failure

### 3. TARIFF card (logged-in only)

```
TARIFF

( ) Agile
( ) Flat rate
    Flat rate (p/kWh) [ 18.2 ]     ← visible only when Flat selected
                            [ Save ]
```

Radio buttons: tapping a row sets `tariffType` immediately (no server call for the radio change alone).
The flat rate text input is visible only when `tariffType === 'flat'`.
"Save" button calls `POST /api/settings` with the current values.
Show a brief "Saved" confirmation text for 2 seconds after success.

### 4. HOME ASSISTANT card (logged-in only)

```
HOME ASSISTANT

Webhook URL
[ https://homeassistant.local/api/webhook/leccy_alert ]
                           [ Test ] [ Save ]

Get setup instructions   >    ← chevron row

Trigger check from HA
POST yourdomain.com/api/webhooks/check
[ Copy URL ]
```

**Webhook URL row**: `TextInput`, `autoCapitalize:'none'`, `autoCorrect:false`, `keyboardType:'url'`.

**"Test" button**: calls `POST /api/settings/test-webhook`.
- While testing: show `ActivityIndicator` inside the button.
- On success: show "OK (200)" in green for 2 seconds.
- On failure: show "Failed — check the URL" in red for 2 seconds.

**"Save" button**: calls `POST /api/settings` with the current webhook URL.

**"Get setup instructions" chevron row**: navigates to `HASetupScreen` — a simple
static screen (add to root stack, no new plan needed) explaining:

```
Setting up Home Assistant

1. In Home Assistant, go to Settings > Automations > Blueprints.

2. Import this blueprint URL:
   yourdomain.com/api/settings/ha-blueprint
   [ Copy blueprint URL ]

3. Create an automation from the blueprint. It will create a webhook
   with the ID "leccy_alert".

4. Your webhook URL will be:
   http://homeassistant.local:8123/api/webhook/leccy_alert
   Paste this into the Webhook URL field above.

When an alert fires, Leccy will POST to this URL. Your automation
can then send a notification, turn on a device, or trigger any
other HA action.
```

Render this as plain `Text` components in a `ScrollView` on a cream background.
Include two "Copy" buttons (using `Clipboard.setStringAsync` from `expo-clipboard`)
for the blueprint URL and the example webhook URL.

Install if not present: `npx expo install expo-clipboard`

**"Trigger check from HA" section**: displays the inbound webhook URL
(`POST https://yourdomain.com/api/webhooks/check`) with a "Copy URL" button.
Add a single line of explanatory text below in secondary colour:
"Call this from an HA automation (e.g. when your car plugs in) to trigger
an immediate alert check without waiting 30 minutes."

### 5. APPEARANCE card (all users)

```
APPEARANCE

( ) System
( ) Light
( ) Dark
```

Radio selection. Persists to `AsyncStorage` (not the server — no auth needed for theme).
Theme changes take effect immediately using React context. Full dark mode implementation
is out of scope for this plan — just save the preference so it is available when dark
mode is implemented.

```typescript
import AsyncStorage from '@react-native-async-storage/async-storage';
const THEME_KEY = 'leccy_theme';

// On change: await AsyncStorage.setItem(THEME_KEY, newTheme);
// On mount: const stored = await AsyncStorage.getItem(THEME_KEY); setTheme(stored || 'system');
```

### 6. ABOUT card (all users)

```
ABOUT

Version  1.0.0            (read from app.json or expo-constants)
Privacy policy       >    (chevron — navigates to a WebView or opens URL in browser)
Data sources         >    (chevron — navigates to DataSourcesScreen)
```

Privacy policy: open `https://yourdomain.com/privacy` in the system browser using
`import { Linking } from 'react-native'; Linking.openURL(url)`.

Data sources: navigate to an inline screen (not a separate plan — build it here):
`DataSourcesScreen` — simple list card with four rows:

```
Elexon BMRS
Half-hourly generation by fuel type

Carbon Intensity API
National and regional carbon intensity

Octopus Energy
Agile tariff half-hourly prices (48h)

Open-Meteo
Hourly weather (Birmingham, 52.48°N 1.90°W)
```

Each row: data source name in 15sp, description in 13sp secondary colour.
Back navigation via React Navigation stack (add `DataSourcesScreen` to the root stack).

### 7. Assembly layout

`ScrollView` with all cards stacked vertically, 16px padding, 12px gap between cards.

Section title above each card (plain text, not SectionLabel):
```
ACCOUNT
TARIFF
HOME ASSISTANT
APPEARANCE
ABOUT
```

Cards that require login (ACCOUNT, TARIFF, HOME ASSISTANT) are hidden entirely
if `!isLoggedIn` — replaced by a single sign-in prompt row in a card:
"Sign in to access settings" with a chevron that navigates to the Login modal.

## Implementation notes

- Use `expo-constants` to read the app version: `import Constants from 'expo-constants'; Constants.expoConfig?.version`.
- The Change Password modal is a `Modal` with `animationType:'slide'` — same pattern
  as LogSessionSheet and AddAlertSheet.
- Theme preference from `AsyncStorage` should be read on mount — add a brief
  `isLoadingTheme` state to avoid a flash.
- Do not implement full dark mode in this plan — just save and read the preference.

## Verification in Expo Go

1. Settings tab shows all five cards (Account shows sign-in link if not logged in).
2. After login: email appears in Account card.
3. Switch tariff to "Flat rate" — flat rate input appears.
4. Enter a flat rate, tap Save — brief "Saved" confirmation.
5. Enter a webhook URL, tap Test — brief "OK" or "Failed" status.
6. Tap "Change password" — modal slides up, form fields appear.
7. Tap "Sign out" — email disappears from Account card; Saved and Alerts show sign-in prompts.
8. Tap "Data sources" — navigates to the data sources list.

---
Done when: A logged-in user can change their tariff type and flat rate (saved to the server), test a webhook URL, and sign out — which immediately clears all auth-gated content across all screens.
