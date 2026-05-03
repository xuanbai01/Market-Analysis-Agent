/**
 * cash-capital-extract tests (Phase 4.3.A).
 *
 * Cross-section helpers for CashAndCapitalCard:
 *
 *   - extractCapexSbcSeries(capAlloc) → 2 MultiLineSeries (CapEx + SBC)
 *   - extractCashDebtSeries(quality)  → 2 MultiLineSeries (Cash + Debt)
 *   - extractNetCashPerShare(quality) → number | null  (cash − debt at latest quarter)
 *
 * Description matches:
 *   Capital Allocation: "Capital expenditure per share",
 *                       "Stock-based compensation per share"
 *   Quality:            "Cash + short-term investments per share",
 *                       "Total debt per share"
 */
import { describe, expect, it } from "vitest";

import {
  extractCapexSbcSeries,
  extractCashDebtSeries,
  extractNetCashPerShare,
} from "./cash-capital-extract";
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

function section(title: string, claims: Claim[]): Section {
  return { title, claims, summary: "", confidence: "high" };
}

const HIST: ClaimHistoryPoint[] = [
  { period: "2024-Q1", value: 10 },
  { period: "2024-Q2", value: 11 },
  { period: "2024-Q3", value: 12 },
  { period: "2024-Q4", value: 13 },
];

// ── extractCapexSbcSeries ────────────────────────────────────────────

describe("extractCapexSbcSeries", () => {
  it("returns CapEx + SBC series from the Capital Allocation section", () => {
    const s = section("Capital Allocation", [
      claim("Capital expenditure per share", 1.41, HIST),
      claim("Stock-based compensation per share", 1.51, HIST),
    ]);
    const series = extractCapexSbcSeries(s);
    expect(series.map((sx) => sx.label)).toEqual(["CapEx", "SBC"]);
    series.forEach((sx) => expect(sx.history).toHaveLength(4));
  });

  it("drops series with empty history", () => {
    const s = section("Capital Allocation", [
      claim("Capital expenditure per share", 1.41, HIST),
      claim("Stock-based compensation per share", null, []),
    ]);
    expect(extractCapexSbcSeries(s).map((sx) => sx.label)).toEqual(["CapEx"]);
  });

  it("returns empty when section has no relevant claims", () => {
    expect(extractCapexSbcSeries(section("Capital Allocation", []))).toEqual([]);
  });
});

// ── extractCashDebtSeries ────────────────────────────────────────────

describe("extractCashDebtSeries", () => {
  it("returns Cash + Debt series from the Quality section", () => {
    const s = section("Quality", [
      claim("Cash + short-term investments per share", 26.84, HIST),
      claim("Total debt per share", 3.92, HIST),
    ]);
    const series = extractCashDebtSeries(s);
    expect(series.map((sx) => sx.label)).toEqual(["Cash", "Debt"]);
    series.forEach((sx) => expect(sx.history).toHaveLength(4));
  });

  it("drops series with empty history", () => {
    const s = section("Quality", [
      claim("Cash + short-term investments per share", 26.84, HIST),
      claim("Total debt per share", null, []),
    ]);
    expect(extractCashDebtSeries(s).map((sx) => sx.label)).toEqual(["Cash"]);
  });
});

// ── extractNetCashPerShare ───────────────────────────────────────────

describe("extractNetCashPerShare", () => {
  it("returns cash − debt at the latest quarter when both are present", () => {
    const s = section("Quality", [
      claim("Cash + short-term investments per share", 26.84),
      claim("Total debt per share", 3.92),
    ]);
    expect(extractNetCashPerShare(s)).toBeCloseTo(22.92, 2);
  });

  it("returns null when cash is missing", () => {
    const s = section("Quality", [claim("Total debt per share", 3.92)]);
    expect(extractNetCashPerShare(s)).toBeNull();
  });

  it("returns null when debt is missing", () => {
    const s = section("Quality", [
      claim("Cash + short-term investments per share", 26.84),
    ]);
    expect(extractNetCashPerShare(s)).toBeNull();
  });

  it("returns null when either value is non-numeric", () => {
    const s = section("Quality", [
      claim("Cash + short-term investments per share", null),
      claim("Total debt per share", 3.92),
    ]);
    expect(extractNetCashPerShare(s)).toBeNull();
  });

  it("supports negative net cash (debt-heavy balance sheet)", () => {
    const s = section("Quality", [
      claim("Cash + short-term investments per share", 2.0),
      claim("Total debt per share", 10.5),
    ]);
    expect(extractNetCashPerShare(s)).toBeCloseTo(-8.5, 2);
  });
});
