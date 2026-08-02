# Plan 6c: Mobile App — Auth Screens

**Objective**: Build login and signup screens, persist the auth token with expo-secure-store, wire up AuthContext so the app knows the user's login state across restarts.
**Requires**: Plan 6a (app shell + AuthContext stub), Plan 1 (backend auth endpoints live at the deployed URL).
**Touches**: `Leccy/src/auth/AuthContext.tsx`, `Leccy/src/screens/LoginScreen.tsx`, `Leccy/src/screens/SignupScreen.tsx`, `Leccy/App.tsx`

---

## Context

Plan 6a created a minimal `AuthContext` stub and the app shell. This plan replaces
the stub with a full implementation: on launch, the app reads any saved token from
secure storage and calls `GET /api/me` to verify it is still valid. The auth screens
use a full-screen layout (cream background, no card) — the form fields float on the
background directly, matching the Leccy auth screen mockup.

**No emojis anywhere** — not in button text, error messages, or placeholders.

## Visual spec

- Background: `#F2EDE6` (cream) — full screen, no card wrapping the form
- Wordmark "Leccy" at the top: `fontSize:28, fontWeight:'700', color:'#1E6B3C'`
- Subtitle: `fontSize:15, color:'#6B7280'`, below the wordmark
- Input fields: white background, `borderRadius:12`, `borderWidth:1`, `borderColor:'#E5E7EB'`, padding 14, `fontSize:15`
- Primary button: background `#1E6B3C`, white text, `borderRadius:12`, padding 16, `fontSize:16, fontWeight:'600'`
- Link text ("Don't have an account? Sign up"): `color:'#1E6B3C'`, `fontSize:14`
- No decorative illustration, no gradient

## What to build

### 1. Replace `src/auth/AuthContext.tsx`

Full implementation with persistent token:

```typescript
import React, { createContext, useContext, useState, useEffect } from 'react';
import * as SecureStore from 'expo-secure-store';
import { setAuthToken, apiFetch } from '../api/client';

const TOKEN_KEY = 'leccy_auth_token';

interface AuthState {
  token:     string | null;
  email:     string | null;
  isLoggedIn: boolean;
  isLoading:  boolean;       // true while checking stored token on launch
  login:  (token: string, email: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState>({ /* ... defaults ... */ });

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [token, setToken]   = useState<string | null>(null);
  const [email, setEmail]   = useState<string | null>(null);
  const [isLoading, setLoading] = useState(true);

  useEffect(() => {
    // On launch: restore token from secure storage and verify it
    (async () => {
      try {
        const stored = await SecureStore.getItemAsync(TOKEN_KEY);
        if (stored) {
          setAuthToken(stored);
          const me = await apiFetch<{ email: string }>('/api/me');
          setToken(stored);
          setEmail(me.email);
        }
      } catch {
        // Token expired or invalid — clear it silently
        await SecureStore.deleteItemAsync(TOKEN_KEY);
        setAuthToken(null);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const login = async (t: string, e: string) => {
    await SecureStore.setItemAsync(TOKEN_KEY, t);
    setAuthToken(t);
    setToken(t);
    setEmail(e);
  };

  const logout = async () => {
    await SecureStore.deleteItemAsync(TOKEN_KEY);
    setAuthToken(null);
    setToken(null);
    setEmail(null);
  };

  return (
    <AuthContext.Provider value={{ token, email, isLoggedIn: !!token, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
```

### 2. `src/screens/LoginScreen.tsx`

Props: `onSwitch: () => void` (called when "Sign up" link is tapped).

State: `email`, `password`, `showPassword` (bool), `loading`, `error`.

Layout (all in a `KeyboardAvoidingView + ScrollView` so the form stays visible when keyboard opens):
1. Spacer (flex: 1) to push content to vertical centre
2. "Leccy" wordmark
3. "Sign in to your account" subtitle
4. Email input (keyboardType "email-address", autoCapitalize "none", autoCorrect false)
5. Password input with show/hide toggle (icon: Feather "eye" / "eye-off")
6. "Sign in" primary button — calls `POST /auth/login`, on success calls `auth.login(token, email)`
7. Error message below button: `color:'#DC2626', fontSize:13` — shows server error or "Invalid email or password"
8. "Don't have an account?" + "Sign up" link
9. "Forgot password?" text link — opens `ForgotPasswordScreen` (see below)

On loading: disable inputs and button, show `ActivityIndicator` inside the button.

### 3. `src/screens/SignupScreen.tsx`

Identical to LoginScreen with:
- Title: "Create your account"
- Extra "Confirm password" field
- Validate `password === confirmPassword` before submitting — show "Passwords do not match" inline
- Calls `POST /auth/signup`; on success calls `auth.login(token, email)`
- "Already have an account?" + "Sign in" link

### 3b. `src/screens/ForgotPasswordScreen.tsx`

Add to root stack navigator alongside LoginScreen and SignupScreen.

State: `email`, `loading`, `submitted` (bool), `error`.

Layout (full-screen cream, same style as LoginScreen):
1. "Leccy" wordmark
2. "Reset your password" subtitle
3. Email input
4. "Send reset link" green button — calls `POST /auth/forgot-password`
5. On success (`submitted = true`): hide the form; show:
   ```
   Check your email
   If an account exists for [email], we sent a reset link.
   It expires in 1 hour.
   ```
   + "Back to sign in" link
6. Error message if the request itself fails (network error only — the endpoint always
   returns 200 regardless of whether the email exists)

**Note**: `POST /auth/forgot-password` only sends an email if `SMTP_HOST` is configured
on the server (Plan 1). If not configured, the endpoint returns `{"ok":true}` but no
email is sent. In that case the user sees the success message but gets no email —
this is a known limitation, documented in the About section of Settings (Plan 6g).

Add `ForgotPasswordScreen` to the root stack in `App.tsx`:
```typescript
<RootStack.Screen name="ForgotPassword" component={ForgotPasswordScreen} />
```

### 4. Update `App.tsx` — conditional navigation

Add a loading state while `AuthContext.isLoading` is true (show a splash/loading screen).

Create a simple auth flow within the app — not a separate navigator. Approach:

```typescript
// Inside App.tsx, wrap the Tab.Navigator with auth state awareness:
// - While isLoading: show a full-screen View with background colour (no flash of content)
// - The Savings and Alerts screens show a "sign-in prompt card" when not logged in
//   (handled inside those screens — NOT by redirecting away from them)
// - LoginScreen and SignupScreen are not tabs — they are shown modally or as a
//   sheet when the user taps "Sign in" from within Savings/Alerts
```

Implementation approach: use a `Modal` or React Navigation `Stack` inside the tab app.
Simplest pattern: add a root `Stack.Navigator` in `App.tsx` with the `Tab.Navigator`
as the first screen and `LoginScreen` / `SignupScreen` as modal screens on top.

```typescript
// App.tsx root structure:
const RootStack = createStackNavigator();

function AppNavigator() {
  return (
    <RootStack.Navigator screenOptions={{ headerShown: false, presentation: 'modal' }}>
      <RootStack.Screen name="Main" component={TabNavigator} />
      <RootStack.Screen name="Login" component={LoginScreen} />
      <RootStack.Screen name="Signup" component={SignupScreen} />
    </RootStack.Navigator>
  );
}
```

Install if not present: `npx expo install @react-navigation/stack react-native-gesture-handler`

### 5. Sign-in prompt card (for Savings and Alerts screens)

Create `src/components/SignInPromptCard.tsx`:

```typescript
// Props: navigation (from useNavigation)
// Renders a white card on the cream background:
//   "Sign in to view your [savings / alerts]"
//   Green "Sign in" button → navigation.navigate('Login')
//   "Create account" text link below → navigation.navigate('Signup')
```

This card is rendered by `SavingsScreen` and `AlertsScreen` when `!auth.isLoggedIn`.

## Implementation notes

- `expo-secure-store` is already installed from Plan 6a.
- The `onSwitch` prop between Login/Signup is handled by the Stack navigator —
  `navigation.replace('Signup')` and `navigation.replace('Login')`.
- On the auth screens, `KeyboardAvoidingView behavior='padding'` on Android and
  `behavior='height'` on iOS — detect with `Platform.OS`.
- The loading state in `AuthContext` prevents a flash where the app briefly shows
  the unauthenticated state before checking the stored token.

## Verification in Expo Go

1. Open app — brief loading moment while token is checked.
2. Tap "Saved" tab — shows the sign-in prompt card (not the savings content).
3. Tap "Sign in" — LoginScreen appears as a modal.
4. Enter valid credentials — modal dismisses, Saved tab now shows content.
5. Background the app, reopen — still logged in (token persisted).
6. Go to Settings, tap "Sign out" (Plan 6g) or manually: call `auth.logout()`.
7. Saved tab shows the sign-in prompt again.

---
Done when: A fresh app install shows the sign-in prompt on the Saved tab, a user can sign up or log in via the modal screens, the token survives an app restart (Expo Go reopen without clearing state), and logging out returns the Saved tab to the prompt.
