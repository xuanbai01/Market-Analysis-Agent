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
 *   - extractGrowthChanges(section)     → { rev, gp, opi, fcf, ocf }
 *                                         where each is `latest / first`
 *                                         (e.g. 6.2 means 6.2× growth).
 */
import { describe, expect, it } from "vitest";

import {
  extractGrowthChanges,
  extractGrowthSeries,
  extractPerSharePanels,
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

// ── extractGrowthChanges (2026-11 chart audit) ──────────────────────

describe("extractGrowthChanges", () => {
  const YEAR: ClaimHistoryPoint[] = [
    { period: "2025-Q3", value: 2.8 },
    { period: "2025-Q4", value: 2.7 },
    { period: "2026-Q1", value: 2.85 },
    { period: "2026-Q2", value: 3.05 },
    { period: "2026-Q3", value: 3.1 },
  ];

  it("compares the latest quarter with the same quarter a year earlier", () => {
    const out = extractGrowthChanges(section([claim("Revenue per share", 3.1, YEAR)]));
    expect(out.rev?.kind).toBe("pct");
    expect(out.rev?.value).toBeCloseTo(3.1 / 2.8 - 1, 6);
    expect(out.rev?.basis).toBe("Q3 '26 vs Q3 '25");
    expect(out.rev?.yearOverYear).toBe(true);
  });

  it("falls back to the change since the first point without a year-earlier quarter", () => {
    const noYearAgo = REV_HIST.filter((p) => p.period !== "2021-Q4");
    const out = extractGrowthChanges(section([claim("Revenue per share", 62, noYearAgo)]));
    expect(out.rev?.value).toBeCloseTo(62 / 10 - 1, 6);
    expect(out.rev?.basis).toBe("since Q1 '21");
    expect(out.rev?.yearOverYear).toBe(false);
  });

  it("states a dollar move when the base is zero or negative", () => {
    const losses: ClaimHistoryPoint[] = [
      { period: "2025-Q3", value: -0.35 },
      { period: "2026-Q3", value: -0.78 },
    ];
    const out = extractGrowthChanges(section([claim("Free cash flow per share", -0.78, losses)]));
    expect(out.fcf?.kind).toBe("usd");
    expect(out.fcf?.value).toBeCloseTo(-0.43, 6);
  });

  it("returns null for a series with fewer than 2 points", () => {
    const out = extractGrowthChanges(
      section([claim("Revenue per share", null, []), claim("Gross profit per share", 1, [{ period: "2026-Q3", value: 1 }])]),
    );
    expect(out.rev).toBeNull();
    expect(out.gp).toBeNull();
  });
});

// ── extractPerSharePanels (2026-11 dogfood #8) ──────────────────────
//
// The five per-share series share one unit ($/share), so the card plots
// actual values on a real axis instead of rebasing to the first quarter
// (which blew up small bases and flipped negative ones).

describe("extractPerSharePanels", () => {
  const FCF_HIST: ClaimHistoryPoint[] = [
    { period: "2025-Q3", value: -0.55 },
    { period: "2025-Q4", value: 0.9 },
    { period: "2026-Q1", value: 0.88 },
  ];

  it("splits income lines from cash-flow lines, in display order", () => {
    const panels = extractPerSharePanels(
      section([
        claim("Revenue per share", 62, REV_HIST),
        claim("Gross profit per share", 43.4, GP_HIST),
        claim("Operating income per share", 30, REV_HIST),
        claim("Operating cash flow per share", 1, FCF_HIST),
        claim("Free cash flow per share", 0.88, FCF_HIST),
      ]),
    );
    expect(panels.income.map((s) => s.label)).toEqual([
      "Revenue",
      "Gross profit",
      "Op income",
    ]);
    expect(panels.cashFlow.map((s) => s.label)).toEqual(["OCF", "FCF"]);
  });

  it("keeps the actual values — no rebasing", () => {
    const panels = extractPerSharePanels(
      section([claim("Revenue per share", 62, REV_HIST)]),
    );
    expect(panels.income[0].history.map((p) => p.value)).toEqual(
      REV_HIST.map((p) => p.value),
    );
  });

  it("keeps negative values (a loss-making first quarter can't flip the line)", () => {
    const panels = extractPerSharePanels(
      section([claim("Free cash flow per share", 0.88, FCF_HIST)]),
    );
    expect(panels.cashFlow[0].history[0].value).toBe(-0.55);
  });

  it("gives every series a short label for the line end", () => {
    const panels = extractPerSharePanels(
      section([
        claim("Revenue per share", 62, REV_HIST),
        claim("Free cash flow per share", 0.88, FCF_HIST),
      ]),
    );
    expect(panels.income[0].shortLabel).toBe("Rev");
    expect(panels.cashFlow[0].shortLabel).toBe("FCF");
  });

  it("drops series with fewer than 2 points", () => {
    const panels = extractPerSharePanels(
      section([
        claim("Revenue per share", 62, [{ period: "2026-Q1", value: 62 }]),
        claim("Gross profit per share", 43.4, GP_HIST),
      ]),
    );
    expect(panels.income.map((s) => s.label)).toEqual(["Gross profit"]);
  });
});
