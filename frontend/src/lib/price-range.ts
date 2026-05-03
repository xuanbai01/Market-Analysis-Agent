/**
 * price-range — slice the hero card's 60-day price feed into the
 * subset matching a sub-3M range pill (1D / 5D / 1M). Phase 4.3.B.1.
 *
 * Background: backend ``GET /v1/market/:ticker/prices`` accepts three
 * cadences (60D / 1Y / 5Y). The hero card's 6 UI pills (1D / 5D / 1M
 * / 3M / 1Y / 5Y) all map to one of those three. Pre-4.3.B.1, the four
 * sub-3M pills (1D / 5D / 1M / 3M) all coerced to ``60D`` and shared
 * the same TanStack query key — clicking 1D / 5D / 1M produced the
 * same 60-bar chart as 3M, which looked like a broken pill.
 *
 * This helper slices the 60D dataset client-side per pill so each one
 * renders a visibly different chart without an extra backend call.
 */
import type { PricePoint } from "./schemas";

export type UiRange = "1D" | "5D" | "1M" | "3M" | "1Y" | "5Y";

/** Approximate trading-day count per pill. 1M ≈ 22 trading days, 5D
 *  ≈ 5, 1D shows the most-recent two points (a single point isn't a
 *  chartable line). 3M maps to the full 60D fetch. */
const TRADING_DAYS: Record<UiRange, number | null> = {
  "1D": 2,
  "5D": 5,
  "1M": 22,
  "3M": null, // pass through — backend already constrained to 60D
  "1Y": null, // backend constrained
  "5Y": null, // backend constrained
};

/**
 * Slice ``data`` to the last N trading days for sub-3M ranges; pass
 * through unchanged for 3M / 1Y / 5Y. ``N`` is the documented
 * approximation per pill. When ``data.length < N`` the helper returns
 * everything available rather than artificially truncating.
 *
 * Always returns a slice of the input (never invents points).
 */
export function sliceForRange(
  data: readonly PricePoint[],
  range: UiRange,
): PricePoint[] {
  const n = TRADING_DAYS[range];
  if (n === null) return data.slice();
  if (data.length <= n) return data.slice();
  return data.slice(data.length - n);
}
