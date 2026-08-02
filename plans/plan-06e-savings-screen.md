# Plan 6e: Mobile App — Savings Screen

**Objective**: Build the Savings screen showing lifetime savings summary, session history, and a "Log a session" bottom sheet; wire up the "Log this run" button in the Schedule screen.
**Requires**: Plan 6a (app shell), Plan 6b (SectionLabel component), Plan 6c (AuthContext), Plan 4 (savings backend endpoints live).
**Touches**: `Leccy/src/screens/SavingsScreen.tsx`, `Leccy/src/components/SavingsRow.tsx`, `Leccy/src/components/LogSessionSheet.tsx`, `Leccy/src/screens/ScheduleScreen.tsx` (wire "Log this run")

---

## Context

The Savings screen requires the user to be logged in. When not logged in, show the
`SignInPromptCard` from Plan 6c in place of all content. When logged in, show the
full screen. The green "LIFETIME SAVED" card is the one full-colour (forest green bg)
card on this screen.

**No emojis anywhere** — not in labels, device names, stat cards, or the log sheet.

## Visual spec

- Background: `#F2EDE6` (cream)
- Lifetime saved card: background `#1E6B3C`, white text, `borderRadius:16`, padding 20
  - Label "LIFETIME SAVED": 11sp, white/70%, letter-spacing 1.2, uppercase
  - Amount: `fontSize:32, fontWeight:'700', color:'#FFFFFF'`
  - Subtitle: "vs flat 27p/kWh over N days" — 13sp, `rgba(255,255,255,0.7)`
- 2x2 stat grid: white cards, `borderRadius:16`, shadow, padding 16
  - Large number: `fontSize:24, fontWeight:'700', color:'#1A1A1A'`
  - Label below: `fontSize:13, color:'#6B7280'`
  - Sub-label: `fontSize:11, color:'#9CA3AF'`
- "Log a session" button: full-width, background `#1E6B3C`, white text, `borderRadius:12`, padding 16
- Session row: white card, rows separated by 1px `#E5E7EB` divider
  - Saving amount: right-aligned, `color:'#00A650'` (live green), `fontSize:15, fontWeight:'600'`
  - Swipe-to-delete: red delete action on swipe left

## What to build

### 1. API types (add to `src/api/types.ts`)

```typescript
export interface SavingsSummary {
  total_saving:   number;
  week_saving:    number;
  month_saving:   number;
  total_sessions: number;
  total_kwh:      number;
}

export interface SavingsSession {
  id:           string;
  device_name:  string;
  start_time:   string;   // ISO8601
  duration_h:   number;
  kwh:          number;
  cost_actual:  number | null;
  cost_optimal: number | null;
  saving:       number | null;
  logged_at:    string;
}
```

### 2. `src/components/SavingsRow.tsx`

Props: `session: SavingsSession`, `onDelete: (id: string) => void`

Renders a single session row inside the history list card.

Layout:
- Row 1: `device_name` (15sp, `#1A1A1A`, left) + date formatted "Sat 6 Jun" (13sp, `#6B7280`, right)
- Row 2: start time + "– " + end time (computed from duration_h) + " · " + kwh formatted to 1dp + " kWh" (13sp, `#9CA3AF`)
- Row 3: avg price "Paid N.Np avg" (13sp, `#6B7280`, left) + saving amount right-aligned

Saving display:
- If `saving` is null: show "–" in secondary colour
- If `saving >= 0`: "£N.NN saved" in `#00A650`
- If `saving < 0`: "£N.NN over" in `#DC2626`

Swipe-to-delete: use `react-native-gesture-handler`'s `Swipeable` or a simple
`TouchableOpacity` delete button revealed on swipe. On confirm, call `onDelete(session.id)`.

### 3. `src/components/LogSessionSheet.tsx`

A bottom sheet rendered as a `Modal` with `animationType='slide'`.
Props:

```typescript
interface LogSessionSheetProps {
  visible:        boolean;
  onClose:        () => void;
  onSaved:        () => void;     // called after successful POST
  prefill?: {
    device_name?:  string;
    start_time?:   string;
    duration_h?:   number;
    kw_rating?:    number;
  };
}
```

Fields:
1. "Device name" — text input, placeholder "EV charge"
2. "Start time" — ISO-formatted datetime string, default to current time rounded to
   nearest 30 minutes. Show as a readable string "Mon 8 Jun, 02:00". Use a text input
   — no native date picker (keeps it simple, avoids platform differences in v1).
3. "Duration (hours)" — numeric input, default 2
4. "Power rating (kW)" — numeric input, default 7.4

"Save session" button (forest green, full width):
- Calls `POST /api/savings` with the four fields
- Shows inline error if the fetch fails
- On success: calls `onSaved()` then `onClose()`

Loading state: disable all inputs and show spinner inside the button.

Sheet visual:
- White background, `borderRadius: {topLeft:20, topRight:20}`, padding 20
- Drag handle: 4x40px `#E5E7EB` rounded pill centred at the top
- Section title "Log a session": 18sp SemiBold
- Inputs: white bg with `borderRadius:8, borderWidth:1, borderColor:'#E5E7EB'`, padding 12

### 4. `SavingsScreen.tsx` — assembly

State:
```typescript
const [summary,  setSummary]  = useState<SavingsSummary | null>(null);
const [sessions, setSessions] = useState<SavingsSession[]>([]);
const [loading,  setLoading]  = useState(false);
const [sheetVisible, setSheet] = useState(false);
const { isLoggedIn } = useAuth();
```

If `!isLoggedIn`: return `<SignInPromptCard />` (from Plan 6c).

On mount and after any save/delete: fetch `GET /api/savings/summary` and `GET /api/savings` in parallel.

Layout (`ScrollView` with pull-to-refresh):
1. Screen title: "Your impact" — `fontSize:24, fontWeight:'700'`
2. Lifetime saved card (green bg)
3. 2x2 stat grid: CO2 avoided / Clean kWh / Sessions / This month
4. "Log a session" full-width button → `setSheet(true)`
5. `SectionLabel "RECENT SESSIONS"` + sessions list card

CO2 avoided calculation (client-side):
- Assume avg UK grid carbon without optimisation: 233 gCO2/kWh (hardcoded constant)
- `co2_avoided_kg = (total_kwh * 0.233) - (sessions.reduce(sum, carbon_during_session))`.
  Since the backend doesn't return per-session carbon, simplify to:
  `co2_avoided_kg ≈ total_kwh * 0.1`  (rough estimate; label as "est.").

"Clean kWh" — just display `total_kwh` formatted with comma separator. Sub-label: "wind + solar".

Delete flow: `DELETE /api/savings/{id}`, remove from local state, no re-fetch needed.

### 5. Wire "Log this run" in ScheduleScreen (from Plan 6d)

In `WindowRow.tsx`, the "Log this run" button was disabled. Now enable it:
- `onPress`: open `LogSessionSheet` with `prefill` from the window data
- Pass `kwRating` from the parent screen as a prop to `WindowRow`
- `ScheduleScreen` must render `LogSessionSheet` and pass `onSaved` → re-fetch savings

## Implementation notes

- `react-native-gesture-handler` is already installed (required by React Navigation).
- Bottom sheet as a `Modal` is simpler than a third-party sheet library — use it.
- "This month" stat in the 2x2 grid = `month_saving` from the summary endpoint.
- Session time range: compute `end_time = new Date(start_time + duration_h * 3600 * 1000)`.
- Pre-fill start time in `LogSessionSheet`: round `new Date()` to nearest 30 min.

## Verification in Expo Go

1. Savings tab shows sign-in prompt when not logged in.
2. After login, screen shows summary stats (all zero if no sessions yet).
3. Tap "Log a session" — bottom sheet slides up with empty form.
4. Fill in a device name, start time, duration, kW — tap "Save session".
5. Sheet closes; session appears in the list; summary stats update.
6. Swipe a session row left — delete appears; tap delete; row disappears.
7. Go to Schedule tab, expand a window row, tap "Log this run" — sheet opens pre-filled.

---
Done when: A logged-in user can tap "Log a session", fill in the form, and see the new session appear in the history list with a saving amount shown in green, and the lifetime saved total increases.
