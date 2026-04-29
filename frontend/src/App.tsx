/**
 * App root. Two-state machine:
 *
 *   not authenticated  →  <LoginScreen />
 *   authenticated      →  <Dashboard />
 *
 * "Authenticated" just means a token is present in localStorage. We
 * trust that token until the API rejects it; on a 401, the dashboard
 * clears it and calls ``onSignOut`` which flips us back to the login
 * screen.
 *
 * No router needed — there are exactly two screens. If/when we add
 * deep-linkable views (e.g. ``/symbol/AAPL``), bring in
 * ``react-router`` then, not now.
 */
import { useEffect, useState } from "react";
import { Dashboard } from "./components/Dashboard";
import { LoginScreen } from "./components/LoginScreen";
import { getStoredToken } from "./lib/auth";

export function App() {
  const [authed, setAuthed] = useState<boolean>(() => !!getStoredToken());

  // Sync to localStorage changes from another tab. If the user signs
  // out in tab A, tab B should bounce to login on its next render.
  useEffect(() => {
    function onStorage() {
      setAuthed(!!getStoredToken());
    }
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  if (!authed) {
    return <LoginScreen onAuthenticated={() => setAuthed(true)} />;
  }
  return <Dashboard onSignOut={() => setAuthed(false)} />;
}
