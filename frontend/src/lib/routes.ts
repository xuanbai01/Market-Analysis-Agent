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
} as const;

export const ROUTE_PATHS = {
  login: "/login",
  landing: "/",
  symbol: "/symbol/:ticker",
  compare: "/compare",
} as const;
