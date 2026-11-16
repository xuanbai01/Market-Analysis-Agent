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
  /** A symbol's options page (ADR 0008); signed in only. */
  options: (ticker: string) => `/options/${ticker.toUpperCase()}`,
  /** The owner's positions, live from tastytrade (ADR 0009); needs the owner key. */
  positions: "/positions",
  /** The owner's trades from the encrypted copy (ADR 0009); needs the owner key. */
  trades: "/trades",
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
  options: "/options/:ticker",
  positions: "/positions",
  trades: "/trades",
  demo: "/demo",
  demoSymbol: "/demo/:ticker",
} as const;
