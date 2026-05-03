/**
 * quality-extract tests (Phase 4.2).
 *
 * Pure functions that pull QualityCard's data out of the Quality
 * Section. Same description-matching philosophy as featured-claim /
 * hero-extract / peer-grouping — backend keys don't survive the
 * Pydantic flatten, so we match on the human-readable descriptions
 * defined in app/services/fundamentals.py::_DESCRIPTIONS.
 *
 * Three extractors:
 *
 *   - extractQualityRings(section) → {roe, roic, fcfMargin}
 *   - extractMarginSeries(section) → 3 series for MultiLine
 *   - extractAllQualityClaims(section) / extractPrimaryQualityClaims(section)
 *     → 6+expand split for the claims table.
 */
import { describe, expect, it } from "vitest";

import {
  extractAllQualityClaims,
  extractMarginSeries,
  extractPrimaryQualityClaims,
  extractQualityRings,
} from "./quality-extract";
import type { Claim, ClaimHistoryPoint, ClaimValue, Section } from "./schemas";

function claim(
  description: string,
  value: ClaimValue,
  history: ClaimHistoryPoint[] = [],
): Claim {
  return {
    description,
    value,
    source: {
      tool: "yfinance.fundamentals",
      fetched_at: "2026-05-03T14:00:00+00:00",
    },
    history,
  };
}

function section(claims: Claim[]): Section {
  return {
    title: "Quality",
    claims,
    summary: "",
    confidence: "high",
  };
}

const HIST: ClaimHistoryPoint[] = [
  { period: "2024-Q1", value: 0.42 },
  { period: "2024-Q2", value: 0.45 },
  { period: "2024-Q3", value: 0.48 },
  { period: "2024-Q4", value: 0.51 },
];

// ── extractQualityRings ──────────────────────────────────────────────

describe("extractQualityRings", () => {
  it("pulls ROE, ROIC, FCF margin by description", () => {
    const s = section([
      claim("Return on equity", 0.32),
      claim("Return on invested capital (TTM)", 0.61),
      claim("Free cash flow margin", 0.42),
    ]);
    expect(extractQualityRings(s)).toEqual({
      roe: 0.32,
      roic: 0.61,
      fcfMargin: 0.42,
    });
  });

  it("returns null fields when claims are missing", () => {
    const s = section([claim("Return on equity", 0.32)]);
    expect(extractQualityRings(s)).toEqual({
      roe: 0.32,
      roic: null,
      fcfMargin: null,
    });
  });

  it("returns null fields for non-numeric values", () => {
    const s = section([
      claim("Return on equity", null),
      claim("Return on invested capital (TTM)", "n/a" as unknown as number),
    ]);
    expect(extractQualityRings(s).roe).toBeNull();
    expect(extractQualityRings(s).roic).toBeNull();
  });
});

// ── extractMarginSeries ──────────────────────────────────────────────

describe("extractMarginSeries", () => {
  it("returns 3 series (gross / operating / FCF margin) with histories", () => {
    const s = section([
      claim("Gross margin", 0.74, HIST),
      claim("Operating margin", 0.48, HIST),
      claim("Free cash flow margin", 0.42, HIST),
    ]);
    const series = extractMarginSeries(s);
    expect(series).toHaveLength(3);
    expect(series.map((sx) => sx.label)).toEqual([
      "Gross margin",
      "Operating margin",
      "FCF margin",
    ]);
    series.forEach((sx) => {
      expect(sx.history).toHaveLength(4);
    });
  });

  it("drops a series whose history is empty", () => {
    const s = section([
      claim("Gross margin", 0.74, HIST),
      claim("Operating margin", 0.48, []),
      claim("Free cash flow margin", 0.42, HIST),
    ]);
    const series = extractMarginSeries(s);
    expect(series).toHaveLength(2);
    expect(series.map((sx) => sx.label).sort()).toEqual([
      "FCF margin",
      "Gross margin",
    ]);
  });

  it("returns an empty list when no margin claims are present", () => {
    expect(extractMarginSeries(section([]))).toEqual([]);
  });

  it("uses distinct accent colors for each series", () => {
    const s = section([
      claim("Gross margin", 0.74, HIST),
      claim("Operating margin", 0.48, HIST),
      claim("Free cash flow margin", 0.42, HIST),
    ]);
    const colors = extractMarginSeries(s).map((sx) => sx.color);
    expect(new Set(colors).size).toBe(colors.length);
  });
});

// ── extractPrimaryQualityClaims / extractAllQualityClaims ───────────

describe("extractPrimaryQualityClaims", () => {
  it("returns the 6 default-display claims by description, in order", () => {
    const all: Claim[] = [
      claim("Return on equity", 0.32),
      claim("Gross margin", 0.74),
      claim("Net profit margin", 0.55),
      claim("Operating margin", 0.48),
      claim("Free cash flow margin", 0.42),
      claim("Return on invested capital (TTM)", 0.61),
      claim("Revenue per share", 50.2),
      claim("Total debt per share", 4.1),
    ];
    const s = section(all);
    const primary = extractPrimaryQualityClaims(s);
    expect(primary.map((c) => c.description)).toEqual([
      "Return on equity",
      "Gross margin",
      "Operating margin",
      "Free cash flow margin",
      "Return on invested capital (TTM)",
      "Net profit margin",
    ]);
  });

  it("skips primary claims that are absent (degrades gracefully)", () => {
    const s = section([
      claim("Return on equity", 0.32),
      claim("Gross margin", 0.74),
    ]);
    const primary = extractPrimaryQualityClaims(s);
    expect(primary).toHaveLength(2);
  });
});

describe("extractAllQualityClaims", () => {
  it("returns every claim in the section in order", () => {
    const all: Claim[] = [
      claim("Return on equity", 0.32),
      claim("Gross margin", 0.74),
      claim("Net profit margin", 0.55),
    ];
    expect(extractAllQualityClaims(section(all))).toHaveLength(3);
  });

  it("returns an empty list when the section has no claims", () => {
    expect(extractAllQualityClaims(section([]))).toEqual([]);
  });
});
