# Plan 6a: Mobile App — Project Setup, Navigation Shell, Theme

**Objective**: Create the Expo/React Native project with five-tab navigation, a theme file, placeholder screens, and push notification permission + token registration wired up from first launch.
**Requires**: Plan 5 complete (backend live at a public HTTPS URL). Plan 3a complete (push-token endpoint exists on the backend).
**Touches**: Creates the entire `Leccy/` directory — all new files.

---

## Context

This is the foundation for all Phase 6 plans. It produces a working app shell that
can be opened in Expo Go and navigated between tabs. Critically, it also handles push
notification permission on launch and registers the Expo push token with the backend
— this must be done in the shell so every subsequent plan can assume push is wired up.

**No emojis anywhere** — not in strings, labels, placeholders, tab labels, or console logs.

## What to build

### 1. Create the project

```bash
npx create-expo-app Leccy --template blank-typescript
cd Leccy
```

### 2. Install dependencies

```bash
npx expo install expo-secure-store
npx expo install expo-font @expo-google-fonts/inter
npx expo install @react-navigation/native @react-navigation/bottom-tabs
npx expo install @react-navigation/stack
npx expo install react-native-safe-area-context react-native-screens
npx expo install react-native-gesture-handler
npx expo install victory-native@^36.9.2   # pin major version — breaking changes between releases
npx expo install @react-native-async-storage/async-storage
npx expo install react-native-svg        # required by victory-native
npx expo install expo-notifications      # push notifications
npx expo install expo-device             # needed by expo-notifications for physical device check
```

### 3. Create `src/theme.ts`

```typescript
export const Colors = {
  // Brand
  forestGreen:    '#1E6B3C',
  liveGreen:      '#00A650',
  blue:           '#3B82F6',
  amber:          '#D97706',
  red:            '#DC2626',

  // Backgrounds
  background:     '#F2EDE6',   // warm cream — never use pure white as page bg
  surface:        '#FFFFFF',
  surfaceDark:    '#1E293B',

  // Text
  textPrimary:    '#1A1A1A',
  textSecondary:  '#6B7280',
  label:          '#9CA3AF',
  border:         '#E5E7EB',

  // Status pills
  pillGreenBg:    '#DCFCE7',
  pillGreenText:  '#166534',
  pillAmberBg:    '#FEF3C7',
  pillAmberText:  '#92400E',
  pillRedBg:      '#FEE2E2',
  pillRedText:    '#991B1B',
  pillGreyBg:     '#F3F4F6',
  pillGreyText:   '#374151',
};

export const FontSize = {
  display:        32,
  headingLarge:   24,
  headingMedium:  18,
  body:           15,
  bodySmall:      13,
  label:          11,
  pill:           11,
};

export const FontWeight = {
  bold:           '700' as const,
  semiBold:       '600' as const,
  medium:         '500' as const,
  regular:        '400' as const,
};

export const Spacing = {
  xs:  4,
  sm:  8,
  md:  16,
  lg:  24,
  xl:  32,
};

export const Card = {
  backgroundColor: Colors.surface,
  borderRadius: 16,
  shadowColor: '#000',
  shadowOffset: { width: 0, height: 2 },
  shadowOpacity: 0.08,
  shadowRadius: 8,
  elevation: 3,
  padding: Spacing.md,
};
```

### 4. Create `src/api/client.ts`

```typescript
// BASE_URL is read from Expo's app.config.js extra field so it can be set at build time
// without editing source files. See app.config.js note in Implementation notes below.
const BASE_URL = (Constants.expoConfig?.extra?.apiUrl as string) ?? 'http://localhost:8000';

let authToken: string | null = null;

export function setAuthToken(token: string | null) {
  authToken = token;
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };
  if (authToken) {
    headers['Authorization'] = `Bearer ${authToken}`;
  }
  const response = await fetch(`${BASE_URL}${path}`, { ...options, headers });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API ${response.status}: ${text}`);
  }
  return response.json() as Promise<T>;
}
```

### 5. Create `src/notifications/pushService.ts`

All push notification logic lives here — imported once from `App.tsx`.

```typescript
import * as Notifications from 'expo-notifications';
import * as Device from 'expo-device';
import { Platform } from 'react-native';
import { apiFetch } from '../api/client';

// How to handle notifications when the app is in the foreground
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: false,
    shouldSetBadge:  false,
  }),
});

/**
 * Request permission and register the Expo push token with the backend.
 * Call this after the user is logged in so the token is associated with their account.
 * Safe to call multiple times — the backend upserts.
 */
export async function registerPushToken(): Promise<void> {
  if (!Device.isDevice) {
    // Push notifications do not work in the simulator — skip silently
    return;
  }

  const { status: existingStatus } = await Notifications.getPermissionsAsync();
  let finalStatus = existingStatus;

  if (existingStatus !== 'granted') {
    const { status } = await Notifications.requestPermissionsAsync();
    finalStatus = status;
  }

  if (finalStatus !== 'granted') {
    // User denied permission — do not retry, do not throw
    return;
  }

  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync('default', {
      name: 'default',
      importance: Notifications.AndroidImportance.MAX,
    });
  }

  const tokenData = await Notifications.getExpoPushTokenAsync();
  const token = tokenData.data;   // e.g. "ExponentPushToken[xxxxxxxxxxxxxxxxxxxxxx]"

  await apiFetch('/api/push-token', {
    method: 'POST',
    body: JSON.stringify({ token }),
  });
}
```

### 6. Create `src/auth/AuthContext.tsx`

Minimal stub for this plan — Plan 6c replaces the login/logout logic. Includes
`registerPushToken` call on login so push is wired up immediately after auth.

```typescript
import React, { createContext, useContext, useState } from 'react';
import { registerPushToken } from '../notifications/pushService';

interface AuthState {
  token:     string | null;
  email:     string | null;
  isLoggedIn: boolean;
  login:  (token: string, email: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthState>({
  token: null, email: null, isLoggedIn: false,
  login: async () => {}, logout: () => {},
});

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);

  const login = async (t: string, e: string) => {
    setToken(t);
    setEmail(e);
    // Register push token now that the user is authenticated
    try { await registerPushToken(); } catch { /* non-fatal */ }
  };

  const logout = () => { setToken(null); setEmail(null); };

  return (
    <AuthContext.Provider value={{ token, email, isLoggedIn: !!token, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
```

### 7. Create placeholder screens

Files to create — all identical structure, different title text:
- `src/screens/NowScreen.tsx` — title: "Home"
- `src/screens/ScheduleScreen.tsx` — title: "Schedule"
- `src/screens/SavingsScreen.tsx` — title: "Saved"
- `src/screens/AlertsScreen.tsx` — title: "Alerts"
- `src/screens/SettingsScreen.tsx` — title: "Settings"

```typescript
import React from 'react';
import { Text, StyleSheet } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Colors, FontSize, FontWeight } from '../theme';

export default function NowScreen() {
  return (
    <SafeAreaView style={styles.container}>
      <Text style={styles.title}>Home</Text>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background, padding: 16 },
  title: { fontSize: FontSize.headingLarge, fontWeight: FontWeight.bold, color: Colors.textPrimary },
});
```

### 8. Create `App.tsx`

```typescript
import 'react-native-gesture-handler';   // must be first import
import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { enableScreens } from 'react-native-screens';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import { AuthProvider } from './src/auth/AuthContext';
import { Colors, FontSize } from './src/theme';

import NowScreen      from './src/screens/NowScreen';
import ScheduleScreen from './src/screens/ScheduleScreen';
import SavingsScreen  from './src/screens/SavingsScreen';
import AlertsScreen   from './src/screens/AlertsScreen';
import SettingsScreen from './src/screens/SettingsScreen';

enableScreens();

const Tab = createBottomTabNavigator();

export default function App() {
  return (
    <SafeAreaProvider>
      <AuthProvider>
        <NavigationContainer>
          <Tab.Navigator
            screenOptions={({ route }) => ({
              headerShown: false,
              tabBarActiveTintColor:   Colors.forestGreen,
              tabBarInactiveTintColor: '#9CA3AF',
              tabBarStyle: {
                backgroundColor: Colors.surface,
                borderTopColor:  Colors.border,
              },
              tabBarLabelStyle: { fontSize: FontSize.label },
              tabBarIcon: ({ color, size }) => {
                const icons: Record<string, string> = {
                  Home: 'home', Schedule: 'calendar', Saved: 'trending-up',
                  Alerts: 'bell', Settings: 'sliders',
                };
                return <Feather name={icons[route.name] as any} size={size} color={color} />;
              },
            })}
          >
            <Tab.Screen name="Home"     component={NowScreen} />
            <Tab.Screen name="Schedule" component={ScheduleScreen} />
            <Tab.Screen name="Saved"    component={SavingsScreen} />
            <Tab.Screen name="Alerts"   component={AlertsScreen} />
            <Tab.Screen name="Settings" component={SettingsScreen} />
          </Tab.Navigator>
        </NavigationContainer>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
```

### 9. Create notification icon asset

**Create `assets/notification-icon.png`** before updating `app.json` — EAS Build will
fail if this file is missing. Requirements: 96x96px, white foreground on transparent
background (Android notification icon spec). A plain white circle or "L" lettermark works.
Create it with any image editor or use ImageMagick:
```bash
convert -size 96x96 xc:transparent -fill white -draw "circle 48,48 48,8" assets/notification-icon.png
```

### 10. Update `app.json`

```json
{
  "expo": {
    "name": "Leccy",
    "slug": "leccy",
    "plugins": [
      [
        "expo-notifications",
        {
          "icon": "./assets/notification-icon.png",
          "color": "#1E6B3C"
        }
      ]
    ]
  }
}
```

## Implementation notes

- `expo-notifications` requires an Expo project ID for production push via EAS.
  During development with Expo Go, it works without one. Before the Play Store build
  (Plan 7), run `eas build:configure` which sets the project ID in `app.json`.
- `registerPushToken()` is called on login, not on app launch, so the token is always
  associated with an authenticated user account. Anonymous push tokens are not supported.
- `react-native-gesture-handler` must be the very first import in `App.tsx`.
- Push notifications from Expo Go use Expo's shared push certificate — this is fine
  for development. The production EAS build uses your own certificate automatically.

## Verification

```bash
cd Leccy
npx expo start
```

1. Install Expo Go on a physical Android device and scan the QR code.
2. All five tabs visible and navigable.
3. Background is cream `#F2EDE6` on every tab.
4. Log in (once Plan 6c is implemented) — confirm the OS permission dialog appears.
5. Grant permission — `POST /api/push-token` request appears in the backend logs.
6. Check `GET /api/alerts/health` — push token row now exists in `app.push_tokens`.

---
Done when: The app opens in Expo Go on a physical Android device, all five tabs navigate correctly with cream background, and after login the Expo push token is registered with the backend (visible in `app.push_tokens` table).
