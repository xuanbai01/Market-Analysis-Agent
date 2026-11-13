/**
 * Demo mode — the public read-only view of a few pre-built reports.
 *
 * The pages under ``/demo`` render the same dashboard as a signed-in
 * visit, but read from the backend's open ``/v1/demo`` routes, which
 * serve only what is already stored for a configured list of tickers
 * (app/services/demo.py). ``DemoShell`` provides ``true``; components
 * that fetch, or that offer an action a visitor can't take (Regenerate,
 * the watchlist star, links to other tickers), ask ``useDemo()``.
 */
import { createContext, useContext } from "react";

export const DemoContext = createContext(false);

/** True inside the public demo pages. */
export function useDemo(): boolean {
  return useContext(DemoContext);
}
