/**
 * Route constants for the Phase 4 dashboard. Centralized so route
 * renames flow through one file and link helpers stay type-safe.
 */

export const ROUTES = {
  login: "/login",
  landing: "/",
  symbol: (ticker: string) => `/symbol/${ticker.toUpperCase()}`,
  /** Phase 4.6 — placeholder until that PR ships. */
  compare: "/compare",
  /** Cross-company lenses (ADR 0007 layer 3). */
  lenses: "/lens",
  lens: (id: string) => `/lens/${encodeURIComponent(id)}`,
  /** Public read-only demo: no sign-in. */
  demo: "/demo",
  demoSymbol: (ticker: string) => `/demo/${ticker.toUpperCase()}`,
} as const;

export const ROUTE_PATHS = {
  login: "/login",
  landing: "/",
  symbol: "/symbol/:ticker",
  compare: "/compare",
  lenses: "/lens",
  lens: "/lens/:id",
  demo: "/demo",
  demoSymbol: "/demo/:ticker",
} as const;
