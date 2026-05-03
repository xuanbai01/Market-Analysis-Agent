/**
 * growth-extract tests (Phase 4.3.A).
 *
 * Pulls 5 per-share history series out of the Quality section
 * (revenue_per_share / gross_profit_per_share / operating_income_per_share
 * / fcf_per_share / ocf_per_share) and rebases each to its first
 * history point = 100 so the multi-line chart shows true relative
 * growth on a shared axis.
 *
 * Two pure helpers:
 *
 *   - extractGrowthSeries(section)      → MultiLineSeries[]
 *   - extractGrowthMultipliers(section) → { rev, gp, opi, fcf, ocf }
 *                                         where each is `latest / first`
 *                                         (e.g. 6.2 means 6.2× growth).
 */
import { describe, expect, it } from "vitest";

import {
  extractGrowthMultipliers,
  extractGrowthSeries,
} from "./growth-extract";
import type { Claim, ClaimHistoryPoint, ClaimValue, Section } from "./schemas";

function claim(
  description: string,
  value: ClaimValue,
  history: ClaimHistoryPoint[] = [],
): Claim {
  return {
    description,
    value,
    source: { tool: "yfinance.fundamentals", fetched_at: "2026-05-03T14:00:00+00:00" },
    history,
  };
}

function section(claims: Claim[]): Section {
  return { title: "Quality", claims, summary: "", confidence: "high" };
}

const REV_HIST: ClaimHistoryPoint[] = [
  { period: "2021-Q1", value: 10 },
  { period: "2021-Q2", value: 12 },
  { period: "2021-Q3", value: 15 },
  { period: "2021-Q4", value: 20 },
  { period: "2022-Q1", value: 25 },
  { period: "2022-Q2", value: 30 },
  { period: "2022-Q3", value: 40 },
  { period: "2022-Q4", value: 62 },
];

const GP_HIST: ClaimHistoryPoint[] = REV_HIST.map((p) => ({
  period: p.period,
  value: p.value * 0.7,
}));

// ── extractGrowthSeries ─────────────────────────────────────────────

describe("extractGrowthSeries", () => {
  it("returns 5 series in canonical order", () => {
    const s = section([
      claim("Revenue per share", 62, REV_HIST),
      claim("Gross profit per share", 43.4, GP_HIST),
      claim("Operating income per share", 24, REV_HIST),
      claim("Free cash flow per share", 21, REV_HIST),
      claim("Operating cash flow per share", 25.5, REV_HIST),
    ]);
    const series = extractGrowthSeries(s);
    expect(series).toHaveLength(5);
    expect(series.map((sx) => sx.label)).toEqual([
      "Revenue",
      "Gross profit",
      "Op income",
      "FCF",
      "OCF",
    ]);
  });

  it("rebases each series so the first point equals 100", () => {
    const s = section([claim("Revenue per share", 62, REV_HIST)]);
    const series = extractGrowthSeries(s);
    expect(series).toHaveLength(1);
    expect(series[0].history[0].value).toBe(100);
    // Last point: (62 / 10) * 100 = 620
    expect(series[0].history[series[0].history.length - 1].value).toBeCloseTo(
      620,
      3,
    );
  });

  it("preserves period labels in the rebased history", () => {
    const s = section([claim("Revenue per share", 62, REV_HIST)]);
    const series = extractGrowthSeries(s);
    expect(series[0].history.map((p) => p.period)).toEqual(
      REV_HIST.map((p) => p.period),
    );
  });

  it("drops a series whose history is empty", () => {
    const s = section([
      claim("Revenue per share", 62, REV_HIST),
      claim("Free cash flow per share", null, []),
    ]);
    const series = extractGrowthSeries(s);
    expect(series.map((sx) => sx.label)).toEqual(["Revenue"]);
  });

  it("drops a series whose first value is zero (can't rebase)", () => {
    const zeroFirst: ClaimHistoryPoint[] = [
      { period: "2021-Q1", value: 0 },
      { period: "2021-Q2", value: 5 },
    ];
    const s = section([claim("Revenue per share", 5, zeroFirst)]);
    expect(extractGrowthSeries(s)).toEqual([]);
  });

  it("returns an empty list when no per-share growth claims are present", () => {
    expect(extractGrowthSeries(section([]))).toEqual([]);
  });
});

// ── extractGrowthMultipliers ────────────────────────────────────────

describe("extractGrowthMultipliers", () => {
  it("returns latest / first for each series", () => {
    const s = section([
      claim("Revenue per share", 62, REV_HIST),
      claim("Gross profit per share", 43.4, GP_HIST),
    ]);
    const mults = extractGrowthMultipliers(s);
    // 62 / 10 = 6.2
    expect(mults.rev).toBeCloseTo(6.2, 3);
    // 43.4 / 7 = 6.2
    expect(mults.gp).toBeCloseTo(6.2, 3);
  });

  it("returns null fields when history is missing or first value is zero", () => {
    const s = section([
      claim("Revenue per share", null, []),
      claim(
        "Gross profit per share",
        0,
        [
          { period: "2021-Q1", value: 0 },
          { period: "2021-Q2", value: 5 },
        ],
      ),
    ]);
    const mults = extractGrowthMultipliers(s);
    expect(mults.rev).toBeNull();
    expect(mults.gp).toBeNull();
  });
});
