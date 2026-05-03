/**
 * App root. Phase 4.0 — router-driven.
 *
 *   /login           → LoginScreen (unauthenticated)
 *   /                → LandingPage (search + recent reports)
 *   /symbol/:ticker  → SymbolDetailPage (the dashboard)
 *
 * Authenticated routes wrap in RequireAuth (redirects to /login when
 * no token is in localStorage) and AppShell (sidebar + main outlet).
 *
 * Compare and other Phase 4.6/4.7 routes are not wired yet; the
 * sidebar shows them disabled.
 */
import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { LandingPage } from "./components/LandingPage";
import { LoginScreen } from "./components/LoginScreen";
import { RequireAuth } from "./components/RequireAuth";
import { SymbolDetailPage } from "./components/SymbolDetailPage";
import { getStoredToken } from "./lib/auth";
import { ROUTES } from "./lib/routes";

/**
 * LoginRoute — wraps LoginScreen with post-auth redirect logic.
 * If the user landed here from a protected route, their original
 * URL is in location.state.from; redirect there on success.
 */
function LoginRoute() {
  const location = useLocation();
  const navigate = useNavigate();
  const from =
    (location.state as { from?: { pathname: string } } | null)?.from?.pathname ??
    ROUTES.landing;

  const [authed, setAuthed] = useState(false);
  useEffect(() => {
    if (authed) navigate(from, { replace: true });
  }, [authed, from, navigate]);

  // If a valid token already exists, skip the login screen entirely.
  if (getStoredToken()) {
    return <Navigate to={from} replace />;
  }

  return <LoginScreen onAuthenticated={() => setAuthed(true)} />;
}

export function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path={ROUTES.login} element={<LoginRoute />} />
        <Route
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route path={ROUTES.landing} element={<LandingPage />} />
          <Route path="/symbol/:ticker" element={<SymbolDetailPage />} />
        </Route>
        {/* Catch-all: anything else bounces to landing (or /login if
            not authed, via the route guard). */}
        <Route path="*" element={<Navigate to={ROUTES.landing} replace />} />
      </Routes>
    </BrowserRouter>
  );
}
