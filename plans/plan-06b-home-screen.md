# Plan 6b: Mobile App — Home Screen

**Objective**: Build the Now screen showing live grid data: best charge window card, 24h price/carbon chart, right-now stats, generation mix donut, and regional carbon list.
**Requires**: Plan 6a complete (navigation shell, theme, api client in place).
**Touches**: `Leccy/src/screens/NowScreen.tsx`, new component files listed below.

---

## Context

The Home screen consumes three backend endpoints: `/api/now`, `/api/fuel-mix`, and
`/api/regional-carbon`. No auth is required for any of these. The screen uses
`ScrollView` with pull-to-refresh. The best charge window card is the only full-colour
(forest green background) card in the app.

**No emojis anywhere** — not in strings, labels, status text, or any UI element.

## Visual spec

From the Voltaic design system:
- Page background: `#F2EDE6` (warm cream)
- Cards: white bg, `borderRadius: 16`, shadow `{shadowColor:'#000', shadowOffset:{width:0,height:2}, shadowOpacity:0.08, shadowRadius:8, elevation:3}`, padding 16
- The best charge window card: background `#1E6B3C`, white text — the ONLY green-bg card on this screen
- Section headers: `fontSize:11, fontWeight:'500', color:'#9CA3AF', letterSpacing:1.2, textTransform:'uppercase'` — rendered above each card
- Chart strokes: 1.5px, price line solid green `#1E6B3C`, carbon line dashed blue `#3B82F6`
- No heavy gridlines on charts — faint horizontal guides only (`stroke:'#E5E7EB'`, `strokeDasharray:'4 4'`)

## What to build

### 1. API response types (add to `src/api/client.ts` or a new `src/api/types.ts`)

```typescript
export interface NowData {
  price_p_kwh: number;
  carbon_gco2: number;
  renewable_pct: number;
  score: number;
  recommendation: string;
  next_best_window: {
    window_start: string;   // ISO8601
    window_end: string;
    score: number;
    price_p_kwh: number;
    carbon_gco2: number;
  } | null;
}

export interface FuelMixRow {
  hour: string;   // ISO8601
  fuel_type: string;
  generation_mw: number;
}

export interface RegionalCarbonRow {
  region_name: string;
  carbon_intensity: number;
  band: string;   // 'very low' | 'low' | 'moderate' | 'high' | 'very high'
}
```

### 2. `src/components/SectionLabel.tsx`

Reusable section header used throughout the app:

```typescript
// Props: label: string
// Renders: uppercase small-caps label + thin divider line below
```

Style: `fontSize:11, fontWeight:'500', color:'#9CA3AF', letterSpacing:1.2, textTransform:'uppercase'`, with a `View` of `height:1, backgroundColor:'#E5E7EB', marginTop:6` below it.

### 3. `src/components/SignalCard.tsx` — best charge window card

Full-colour forest green card. Props:

```typescript
interface SignalCardProps {
  windowStart: string;   // formatted: "Tonight at 02:00"
  windowEnd:   string;   // formatted: "finishes 06:00"
  subtitle:    string;   // e.g. "Strong wind overnight"
  costLabel:   string;   // e.g. "£1.24"
  saveLabel:   string;   // e.g. "£7.61"
  carbonLabel: string;   // e.g. "58g"
}
```

Layout matches the Home screen mockup:
- Background: `#1E6B3C`, borderRadius 16, padding 20
- Large time text: `fontSize:28, fontWeight:'700', color:'#FFFFFF'`
- Subtitle row: `fontSize:13, color:'rgba(255,255,255,0.7)'`
- Three-column stat row: COST / SAVE / CARBON labels at 11sp, values at 18sp SemiBold, white
- "Schedule charge" button at the bottom: white background, `#1E6B3C` text, borderRadius 10, padding 12

If `next_best_window` is null, show: "No upcoming data available" centred in the card.

### 4. `src/components/StatBar.tsx` — right-now three-stat row

White card with three equal-width columns. Props:

```typescript
interface StatBarProps {
  items: Array<{ value: string; label: string }>
}
```

Each column: large value text (18sp SemiBold, `#1A1A1A`), small label below (11sp, `#9CA3AF`).
Card uses the standard white card style from `theme.ts`.

### 5. `src/components/DonutChart.tsx` — generation mix

Uses `victory-native`:

```typescript
import { VictoryPie } from 'victory-native';
```

Props: `data: Array<{x: string, y: number}>` (fuel type + MW).

Fuel type colour mapping (use these exact colours):
```typescript
const FUEL_COLORS: Record<string, string> = {
  WIND:     '#3B82F6',
  NUCLEAR:  '#8B5CF6',
  GAS:      '#D97706',
  SOLAR:    '#F59E0B',
  HYDRO:    '#06B6D4',
  BIOMASS:  '#10B981',
  COAL:     '#6B7280',
  IMPORTS:  '#9CA3AF',
};
```

Centre text: total GW (sum of all fuel types / 1000, formatted to 1dp, e.g. "28.4 GW").
Legend: scrollable list of rows to the right of the donut — fuel name left, percentage right.
Aggregate all fuels with < 2% share into "Other".

### 6. `src/components/PriceChart.tsx` — 24h price + carbon line chart

Uses `victory-native`:
- `VictoryChart` with two `VictoryLine` series
- X-axis: time labels every 4h, formatted as "HH:00"
- Price line: solid, `#1E6B3C`, strokeWidth 1.5
- Carbon line: dashed `strokeDasharray="4 4"`, `#3B82F6`, strokeWidth 1.5
- Very light area fill under the price line: `VictoryArea` with `fillOpacity:0.08`
- No fill under the carbon line
- Grid: `VictoryAxis` with `style={{grid:{stroke:'#E5E7EB', strokeDasharray:'4 4'}}}` for horizontal only
- Legend above the chart: two items — "price" (green) and "carbon" (blue), label size

Props: `rows: Array<{period_utc: string, price_p_kwh: number, carbon_intensity: number}>`
Source: `/api/prices-carbon` — use the last 48 rows (today + yesterday) for the 24h view.

### 7. `src/components/RegionalCarbonList.tsx`

White card. Renders `RegionalCarbonRow[]` sorted by `carbon_intensity ASC`.
Each row:
- Region name: left-aligned, 15sp
- Carbon value: centre, 15sp, `#6B7280`
- Pill badge: right-aligned

Pill colour from `band`:
- `very low` / `low` → green pill
- `moderate` → amber pill
- `high` / `very high` → red pill

Pill text: title-case the `band` value.

### 8. `NowScreen.tsx` — assemble

Replace the placeholder with the full screen:

```typescript
export default function NowScreen() {
  const [nowData, setNowData] = useState<NowData | null>(null);
  const [fuelMix, setFuelMix] = useState<FuelMixRow[]>([]);
  const [regional, setRegional] = useState<RegionalCarbonRow[]>([]);
  const [refreshing, setRefreshing] = useState(false);

  const loadAll = async () => { /* parallel fetches */ };

  useEffect(() => { loadAll(); }, []);

  // Greeting: "Good morning/afternoon/evening, [user name or ""]"
  // Date: "Monday 8 June"
  // ...render SignalCard, StatBar, PriceChart, DonutChart, RegionalCarbonList
}
```

Order of elements (scroll view):
1. Greeting header (date + "Good morning")
2. `SectionLabel` "BEST CHARGE WINDOW" + `SignalCard`
3. `SectionLabel` "NEXT 24 HOURS" + `PriceChart`
4. `SectionLabel` "RIGHT NOW" + `StatBar` (price, carbon, renewable%)
5. `SectionLabel` "GENERATION MIX" + `DonutChart`
6. `SectionLabel` "REGIONAL CARBON" + `RegionalCarbonList`

Pull-to-refresh: `ScrollView refreshControl={<RefreshControl refreshing={refreshing} onRefresh={...} tintColor={Colors.forestGreen} />}`

Score → signal colour:
```typescript
function scoreColor(score: number): string {
  if (score >= 75) return '#00A650';
  if (score >= 40) return '#D97706';
  return '#DC2626';
}
```

Greeting time-of-day:
```typescript
function greeting(): string {
  const h = new Date().getHours();
  if (h < 12) return 'Good morning';
  if (h < 18) return 'Good afternoon';
  return 'Good evening';
}
```

## Implementation notes

- Fetch all three endpoints in parallel using `Promise.all`.
- Show a loading spinner (`ActivityIndicator color={Colors.forestGreen}`) while data is loading.
- Show an error message (not a crash) if any fetch fails — display the other sections that did load.
- Fuel mix data comes as individual rows per fuel type per hour. Aggregate to the most
  recent hour: `GROUP BY fuel_type` keeping latest `hour`, then sum MW.
- Do not use any emoji in greeting text, loading text, or error messages.

**Offline / stale data handling**: cache the last successful API response in
`AsyncStorage` so the screen is useful when the user has no internet (common
at midnight when checking if they should charge):

```typescript
import AsyncStorage from '@react-native-async-storage/async-storage';

const CACHE_KEY = 'home_cache';

// After successful fetch, save to cache:
await AsyncStorage.setItem(CACHE_KEY, JSON.stringify({ nowData, fuelMix, regional, cachedAt: Date.now() }));

// On mount, load cache first, then attempt live fetch:
const raw = await AsyncStorage.getItem(CACHE_KEY);
if (raw) {
  const cached = JSON.parse(raw);
  setNowData(cached.nowData);
  setFuelMix(cached.fuelMix);
  setRegional(cached.regional);
  setCachedAt(cached.cachedAt);
}
```

When showing cached data, display a subtle banner below the greeting:
```
Last updated 14 min ago   (label size, #9CA3AF)
```
Calculate: `Math.round((Date.now() - cachedAt) / 60000)` minutes ago.
Hide the banner when live data has loaded successfully.

## Verification in Expo Go

1. Open the app on a real device with the backend live.
2. Home tab loads and shows the green best charge window card with real data.
3. All five sections are visible when scrolling.
4. Pull-to-refresh re-fetches data (loading indicator appears briefly).
5. Donut chart renders with correct fuel type colours.
6. Regional carbon rows are sorted low → high.
7. Background is cream `#F2EDE6`, not white.

---
Done when: The Home screen renders all five sections with live data from the deployed backend, pull-to-refresh works, and the best charge window card shows the correct next window time in white text on the forest green background.
