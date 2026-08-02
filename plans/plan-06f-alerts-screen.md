# Plan 6f: Mobile App — Alerts Screen

**Objective**: Build the Alerts screen with a list of the user's alerts, toggle switches, swipe-to-delete, and an "Add alert" bottom sheet.
**Requires**: Plan 6a (app shell), Plan 6c (AuthContext, SignInPromptCard), Plan 3a (alerts CRUD endpoints live).
**Touches**: `Leccy/src/screens/AlertsScreen.tsx`, `Leccy/src/components/AlertRow.tsx`, `Leccy/src/components/AddAlertSheet.tsx`

---

## Context

The Alerts screen requires login. When not logged in, show `SignInPromptCard` from
Plan 6c. Alerts are delivered by the backend server-side (Plan 3b) — the app is not
polling in the background; it just manages the alert list via CRUD. The screen is
simple: a list card with toggle rows and a bottom sheet for adding new alerts.

**No emojis anywhere** — not in alert type labels, threshold descriptions, or placeholders.

## Visual spec

- Background: `#F2EDE6` (cream)
- Alerts list: white card, `borderRadius:16`, shadow, alerts separated by `height:1, backgroundColor:'#E5E7EB'` dividers
- Toggle switch: use React Native's built-in `Switch` component — `trackColor={{false:'#E5E7EB', true:'#1E6B3C'}}`, `thumbColor:'#FFFFFF'`
- Row layout: alert description (left, flex:1) + Switch (right)
- "+" Add button: top-right in the screen header area — `color:'#1E6B3C', fontSize:16, fontWeight:'600'`
- Bottom sheet: same spec as LogSessionSheet in Plan 6e (white, top-rounded modal)

## What to build

### 1. API types (add to `src/api/types.ts`)

```typescript
export interface Alert {
  id:            string;
  alert_type:    'price_below' | 'carbon_below' | 'good_window';
  threshold:     number;
  label:         string | null;
  enabled:       boolean;
  quiet_from:    string | null;   // "HH:MM"
  quiet_to:      string | null;
  last_fired_at: string | null;
}
```

### 2. `src/components/AlertRow.tsx`

Props: `alert: Alert`, `onToggle: (id: string) => void`, `onDelete: (id: string) => void`

Collapsed layout (single list row):
- Line 1: human description of the alert (see formatting below), `fontSize:15, color:'#1A1A1A'`
- Line 2: quiet hours description or "No quiet hours" — `fontSize:13, color:'#6B7280'`
- Right: React Native `Switch`, `value={alert.enabled}`, `onValueChange={() => onToggle(alert.id)}`

Swipe-to-delete: `Swipeable` from `react-native-gesture-handler`. Reveal a red
delete action (`backgroundColor:'#DC2626'`, white text "Delete") on swipe left.
On tap delete: call `onDelete(alert.id)`.

Alert description formatting (no emojis):
```typescript
function alertDescription(alert: Alert): string {
  switch (alert.alert_type) {
    case 'price_below':   return `Price below ${alert.threshold}p/kWh`;
    case 'carbon_below':  return `Carbon below ${alert.threshold} gCO2/kWh`;
    case 'good_window':   return `Good window  score > ${alert.threshold}`;
  }
}

function quietDescription(alert: Alert): string {
  if (!alert.quiet_from || !alert.quiet_to) return 'No quiet hours';
  return `Quiet ${alert.quiet_from} – ${alert.quiet_to}`;
}
```

### 3. `src/components/AddAlertSheet.tsx`

A bottom sheet (`Modal`, `animationType:'slide'`). Props: `visible`, `onClose`, `onSaved`.

```typescript
interface AddAlertSheetProps {
  visible:  boolean;
  onClose:  () => void;
  onSaved:  () => void;
}
```

Fields:

**Alert type** — radio-style selection (three options as pressable rows with a dot indicator):
```
( ) Price below        threshold input: [  12  ] p/kWh
( ) Carbon below       threshold input: [ 150  ] gCO2/kWh
( ) Good window        threshold input: [  75  ] score (0-100)
```

Only one type selected at a time. The threshold input appears next to the selected option.
The other two options' threshold inputs are hidden.

**Quiet hours** — `Switch` to enable. When enabled, show two text inputs:
```
From [ 22:00 ]  to  [ 07:00 ]
```
Both use the format "HH:MM". Validate with regex `^\d{2}:\d{2}$` before submitting.

**"Save alert" button** — forest green, full width. Calls `POST /api/alerts` with:
```json
{
  "alert_type": "price_below",
  "threshold": 12.0,
  "quiet_from": "22:00",
  "quiet_to": "07:00"
}
```
`quiet_from`/`quiet_to` are omitted if quiet hours is disabled.

On success: call `onSaved()` and `onClose()`.

Sheet layout (same as LogSessionSheet):
- Drag handle at top
- Title: "Add alert" — 18sp SemiBold
- Alert type section with radio rows
- Quiet hours section with toggle + time inputs (visible only when toggle on)
- Save button

### 4. `AlertsScreen.tsx` — assembly

State:
```typescript
const [alerts,  setAlerts]  = useState<Alert[]>([]);
const [loading, setLoading] = useState(false);
const [sheetVisible, setSheet] = useState(false);
const { isLoggedIn } = useAuth();
```

If `!isLoggedIn`: return `<SignInPromptCard />`.

Load: fetch `GET /api/alerts` on mount.

Header row (inside the screen, not React Navigation header):
- "Alerts" title — `fontSize:24, fontWeight:'700'`
- "+ Add" button right-aligned — triggers `setSheet(true)`

Alerts list card:
- White card, borderRadius 16, shadow
- If `alerts.length === 0`: show "No alerts set. Tap + Add to create one." in secondary colour
- Otherwise: `alerts.map((a, i) => <AlertRow key={a.id} ... />)` with dividers between rows

Toggle: call `PATCH /api/alerts/{id}/toggle`, then optimistically update local state
(flip `enabled` immediately, revert if the request fails).

Delete: call `DELETE /api/alerts/{id}`, remove from local `alerts` state.

After adding (onSaved): re-fetch `GET /api/alerts`.

## Implementation notes

- `Swipeable` from `react-native-gesture-handler` requires the gesture handler installed at
  the root (done via `gestureHandlerRootHOC` or wrapping App.tsx — check if Plan 6c's
  stack navigator already requires this; if so, it should already be in place).
- Optimistic toggle: update state before the API responds. On API error, show a
  brief error message and revert: `setAlerts(prev => prev.map(a => a.id === id ? {...a, enabled: !a.enabled} : a))`.
- The threshold input for each alert type should default to sensible values:
  price_below → 12, carbon_below → 150, good_window → 75.
- Quiet hours inputs: `keyboardType:'numeric'` — user types "22" and "00" in separate
  fields, OR use a single text field with format validation. Single field is simpler.

## Verification in Expo Go

1. Alerts tab shows sign-in prompt when not logged in.
2. After login, shows "No alerts set." message.
3. Tap "+ Add" — sheet slides up. Select "Price below", set threshold to 10.
4. Enable quiet hours, set 22:00 to 07:00.
5. Tap "Save alert" — sheet closes, alert appears in list.
6. Toggle the switch — alert goes from ON to OFF, switch updates immediately.
7. Swipe the row left — "Delete" appears; tap it — row disappears.

---
Done when: A logged-in user can add a "Price below 10p/kWh" alert with quiet hours, see it in the list with the toggle ON, toggle it off, and delete it — all without a full page reload.
