/**
 * price-range — slice the hero card's price feeds into exactly the span
 * each range pill names. Phase 4.3.B.1; calendar ranges 2026-11.
 *
 * The backend serves three feeds (``GET /v1/market/:ticker/prices``):
 * 60D (~90 calendar days), 1Y (400 days) and 5Y (2,000 days) — padded so
 * its cache-coverage check has room. The pills slice them client-side:
 *
 *   5D / 1M   the last 5 / 22 bars of the 60D feed
 *   3M        the whole 60D feed
 *   YTD       the 1Y feed from the previous year's last close
 *   1Y / 5Y   the 1Y / 5Y feed from the last close on or before the
 *             date one / five years before the latest bar
 *
 * Calendar ranges start from a close *before* the period (the base the
 * change is measured from), so the line's first point and the headline
 * % agree with how year-to-date and one-year returns are quoted. Until
 * 2026-11 the 1Y and 5Y pills drew the padded feeds whole — 13 months
 * and 5½ years. There is no 1D: the feed is daily closes, so "1D" drew a
 * straight line between two of them.
 *
 * Always returns a slice of the input (never invents points); periods
 * come from the data's latest bar, not the clock.
 */
import type { PricePoint } from "./schemas";

export type UiRange = "5D" | "1M" | "3M" | "YTD" | "1Y" | "5Y";

/** Bars kept for the bar-count ranges. */
const LAST_BARS: Partial<Record<UiRange, number>> = { "5D": 5, "1M": 22 };

/** Years back for the trailing calendar ranges. */
const YEARS_BACK: Partial<Record<UiRange, number>> = { "1Y": 1, "5Y": 5 };

/** The bars after ``cutoff``, led by the last bar at or before it (the
 *  base the period's change is measured from) when the feed has one. */
function sliceFrom(data: readonly PricePoint[], cutoff: number): PricePoint[] {
  const firstAfter = data.findIndex((p) => Date.parse(p.ts) > cutoff);
  if (firstAfter === -1) return data.slice(-1);
  return data.slice(Math.max(0, firstAfter - 1));
}

export function sliceForRange(data: readonly PricePoint[], range: UiRange): PricePoint[] {
  if (data.length === 0) return [];
  const latest = new Date(data[data.length - 1].ts);

  if (range === "YTD") {
    // Anything dated before 1 January of the latest bar's year is the
    // previous year; its last close is the base.
    return sliceFrom(data, Date.UTC(latest.getUTCFullYear(), 0, 1) - 1);
  }
  const years = YEARS_BACK[range];
  if (years !== undefined) {
    const cutoff = new Date(latest);
    cutoff.setUTCFullYear(cutoff.getUTCFullYear() - years);
    return sliceFrom(data, cutoff.getTime());
  }
  const n = LAST_BARS[range];
  if (n === undefined || data.length <= n) return data.slice();
  return data.slice(data.length - n);
}
