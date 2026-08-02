# Plan 6d: Mobile App — Schedule Screen

**Objective**: Build the Schedule screen with a 2x2 "Optimise for" mode selector, duration and power inputs, an auto-computed plan card, and a scrollable best-windows list.
**Requires**: Plan 6a (app shell, theme, api client). No auth required for this screen.
**Touches**: `Leccy/src/screens/ScheduleScreen.tsx`, new component files listed below.

---

## Context

The Schedule screen answers "when is the best time to run my appliance?" It uses two
existing backend endpoints: `/api/appliance-windows?hours=X` and `/api/best-windows`.
No auth is required. The "Log this run" button in each window row pre-fills the Savings
log sheet — that sheet is defined in Plan 6e; in this plan, leave "Log this run" as a
visible but disabled button (no action yet). Plan 6e will wire it up.

**No emojis anywhere** — not in mode labels, time text, status text, or placeholders.

## Visual spec

- Background: `#F2EDE6` (cream)
- Mode tiles: white cards in a 2x2 grid, `borderRadius:12`, padding 16. Active tile:
  `borderWidth:2, borderColor:'#1E6B3C'`, background `#F0FDF4` (very light green tint).
  Inactive: `borderColor:'#E5E7EB'`, white bg.
- Duration pills: row of pill buttons. Active: background `#1E6B3C`, white text.
  Inactive: white bg, `#1A1A1A` text, border `#E5E7EB`.
- Plan result card: white, standard card spec (borderRadius 16, shadow, padding 16).
- Best windows list: white card with rows separated by a 1px `#E5E7EB` divider.
- Section headers: `SectionLabel` component from Plan 6b.

## What to build

### 1. API types

```typescript
export interface ApplianceWindow {
  window_start: string;   // ISO8601
  window_end:   string;
  score:        number;
  price_p_kwh:  number;
  carbon_gco2:  number;
  cost_est_gbp: number | null;   // computed if kw_rating provided
}

export interface BestWindow {
  window_start: string;
  score:        number;
  price_p_kwh:  number;
  carbon_gco2:  number;
}
```

### 2. Mode definitions

```typescript
type OptimiseMode = 'smart' | 'cheapest' | 'greenest' | 'now';

const MODES: Record<OptimiseMode, { label: string; subtitle: string }> = {
  smart:    { label: 'Smart',    subtitle: 'cost + carbon' },
  cheapest: { label: 'Cheapest', subtitle: 'price only' },
  greenest: { label: 'Greenest', subtitle: 'carbon only' },
  now:      { label: 'Run now',  subtitle: 'skip optimising' },
};
```

The `/api/appliance-windows` endpoint does not accept a mode parameter — it always
returns windows ranked by the combined score. For "Run now" mode, show the current
half-hour window only. For "cheapest" / "greenest", re-sort the returned windows
client-side by `price_p_kwh ASC` or `carbon_gco2 ASC` before displaying.

### 3. `src/components/ModeTileGrid.tsx`

Props: `selected: OptimiseMode`, `onSelect: (mode: OptimiseMode) => void`

2x2 grid using a `View` with `flexDirection:'row', flexWrap:'wrap'`:
- Each tile: 50% width minus spacing, touch feedback via `Pressable`
- Title text: `fontSize:15, fontWeight:'600', color:'#1A1A1A'`
- Subtitle text: `fontSize:13, color:'#6B7280'`
- Active border: `#1E6B3C`, 2px
- Tapping a tile calls `onSelect(mode)` immediately — the plan recalculates

### 4. `src/components/DurationPills.tsx`

Props: `selected: number` (hours), `onSelect: (h: number) => void`
Options: `[1, 2, 3, 4]`

Row of four pill `Pressable` components. Active pill: bg `#1E6B3C`, text white.
Inactive: bg white, border `#E5E7EB`, text `#1A1A1A`.

### 5. `src/components/WindowRow.tsx`

Renders one window from the best-windows list. Props:

```typescript
interface WindowRowProps {
  window:     ApplianceWindow | BestWindow;
  kwRating:   number;
  expanded:   boolean;
  onToggle:   () => void;
  onLogRun:   () => void;   // disabled in this plan
}
```

Collapsed state (single row):
- Left: time formatted as "02:00 – 06:00"
- Centre: `Score [N]` in the score signal colour
- Right: `[N.Np]  [Ng]` (price and carbon)

Expanded state (shown below the row):
- 30-min price breakdown: if the window spans multiple 30-min slots, list each slot's
  price. If the endpoint doesn't return slot-level data, show the average price per slot.
- "Log this run" button: `color:'#1E6B3C'`, text only (no bg), disabled and greyed
  out until Plan 6e wires it up: `opacity:0.4, disabled:true`

### 6. `ScheduleScreen.tsx` — assembly

State:
```typescript
const [mode, setMode]         = useState<OptimiseMode>('smart');
const [durationH, setDuration] = useState<number>(2);
const [kwRating, setKw]       = useState<string>('7.4');
const [windows, setWindows]   = useState<ApplianceWindow[]>([]);
const [bestAll, setBestAll]   = useState<BestWindow[]>([]);
const [loading, setLoading]   = useState(false);
const [expandedIdx, setExpanded] = useState<number | null>(null);
```

Fetch logic:
- `useEffect` triggered by `[durationH]` — fetches `/api/appliance-windows?hours=${durationH}`
- Best windows: fetch `/api/best-windows` once on mount
- When `mode` changes, re-sort `windows` client-side (no new fetch needed)
- "Run now" mode: filter `windows` to only the first entry (current half-hour)

Layout (in a `ScrollView`):
1. Screen title: "Plan a charge" — `fontSize:24, fontWeight:'700'`
2. `SectionLabel "OPTIMISE FOR"` + `ModeTileGrid`
3. "Duration" label + `DurationPills`
4. "Power (kW)" label + `TextInput` (numeric keyboard, default "7.4")
5. `SectionLabel "PLAN"` + plan result card (shows the top window for the selected duration/mode)
6. `SectionLabel "BEST WINDOWS"` + Today/Tomorrow inline tab + window list

**Plan result card** (white, standard card spec):
- Top: start → end time in `fontSize:24, fontWeight:'700'`
- Three-column stat row: COST / CO2 / SAVING (vs flat 27p/kWh)
- COST = top window's avg price × kWh / 100
- CO2 = top window's carbon × kWh / 1000 (kg)
- SAVING = (27 - top window avg price) × kWh / 100 (using 27p as the default flat rate comparison)
- If no windows available: "No data available for this duration."

**Today/Tomorrow inline tab:**
- Two text buttons side by side, no border/bg — active tab: `color:'#1E6B3C', borderBottomWidth:2`
- "Today" shows windows from `/api/best-windows` where `window_start` is today's date
- "Tomorrow" shows windows where `window_start` is tomorrow's date

## Implementation notes

- Parse `kwRating` from the TextInput as `parseFloat` — if not a valid number, treat as 0.
- `window_start` from the API is ISO8601 UTC. Format for display using `new Date(str).toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'})`.
- The top window in the PLAN card is `windows[0]` after applying mode-based sorting.
- Do not fetch on every keystroke for kW rating — recalculate the PLAN card values
  purely client-side using the already-fetched window prices.

## Verification in Expo Go

1. Schedule tab opens with "Smart" mode active (green border on Smart tile).
2. Tapping "Cheapest" mode immediately re-sorts the windows list.
3. Changing duration from 2h to 4h triggers a new API fetch and updates the plan card.
4. Entering a kW value updates COST and SAVING in the plan card.
5. Tapping a window row expands it to show "Log this run" (greyed out).
6. Today/Tomorrow tabs filter the best windows list correctly.

---
Done when: All four mode tiles are selectable, duration pills update the plan card, the PLAN card shows cost/CO2/saving for the top window, and the best windows list renders with expandable rows.
