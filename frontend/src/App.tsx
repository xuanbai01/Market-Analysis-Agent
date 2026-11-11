/**
 * App root. Phase 4.0 — router-driven. Phase 4.6 — Compare lazy-loaded.
 * Phase 4.7 — SymbolDetailPage also lazy-loaded for bundle hygiene.
 *
 *   /login           → LoginScreen (unauthenticated; stays in main)
 *   /                → LandingPage (entry; stays in main)
 *   /symbol/:ticker  → SymbolDetailPage (lazy chunk; Phase 4.7)
 *   /compare         → ComparePage (lazy chunk; Phase 4.6.A)
 *   /lens, /lens/:id → lens index + LensPage (lazy chunks; ADR 0007 layer 3)
 *
 * Authenticated routes wrap in RequireAuth (redirects to /login when
 * no token is in localStorage) and AppShell (sidebar + main outlet).
 *
 * The lazy splits keep main bundle under the 100 KB gz budget.
 * SymbolDetailPage's tree pulls in every Strata card primitive +
 * extractor — that's ~20-25 KB gz of code that only matters when the
 * user opens a ticker. Moving it out of main makes the entry feel
 * snappier and gives Phase 4.8 / future phases plenty of headroom.
 */
import { Suspense, useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";

import { AppShell } from "./components/AppShell";
import { LandingPage } from "./components/LandingPage";
import { LoadingState } from "./components/LoadingState";
import { LoginScreen } from "./components/LoginScreen";
import { RequireAuth } from "./components/RequireAuth";
import { getStoredToken } from "./lib/auth";
import { lazyWithReload } from "./lib/lazy-with-reload";
import { ROUTE_PATHS, ROUTES } from "./lib/routes";

const ComparePage = lazyWithReload(() => import("./components/compare/ComparePage"));
// Cross-company lenses (ADR 0007 layer 3) — their own chunks.
const LensIndexPage = lazyWithReload(() => import("./components/lens/LensIndexPage"));
const LensPage = lazyWithReload(() => import("./components/lens/LensPage"));
const SymbolDetailPage = lazyWithReload(() => import("./components/SymbolDetailPage"));

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
          <Route
            path="/symbol/:ticker"
            element={
              <Suspense fallback={<LoadingState />}>
                <SymbolDetailPage />
              </Suspense>
            }
          />
          <Route
            path={ROUTES.compare}
            element={
              <Suspense fallback={<LoadingState />}>
                <ComparePage />
              </Suspense>
            }
          />
          <Route
            path={ROUTE_PATHS.lenses}
            element={
              <Suspense fallback={null}>
                <LensIndexPage />
              </Suspense>
            }
          />
          <Route
            path={ROUTE_PATHS.lens}
            element={
              <Suspense fallback={null}>
                <LensPage />
              </Suspense>
            }
          />
        </Route>
        {/* Catch-all: anything else bounces to landing (or /login if
            not authed, via the route guard). */}
        <Route path="*" element={<Navigate to={ROUTES.landing} replace />} />
      </Routes>
    </BrowserRouter>
  );
}
