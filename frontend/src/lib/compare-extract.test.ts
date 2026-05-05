/**
 * compare-extract tests (Phase 4.6.A).
 *
 * The Compare page reads two reports and pairs metrics across them.
 * These extractors are pure helpers (no React) so the failing tests
 * pin the contract before the implementation lands.
 *
 * Coverage:
 *   - extractCompareHeroData — name / sector / market cap per ticker
 *   - extractCompareValuationMetrics — 3 cells, lowerIsBetter=true
 *   - extractCompareQualityMetrics — 4 cells, lowerIsBetter=false
 *   - extractCompareMarginOverlay — up to 2 series (operating margin)
 *   - extractCompareGrowthOverlay — up to 4 series (Rev + FCF per side, rebased)
 */
import { describe, expect, it } from "vitest";

import {
  COMPARE_COLOR_A,
  COMPARE_COLOR_B,
  extractCompareGrowthOverlay,
  extractCompareHeroData,
  extractCompareMarginOverlay,
  extractCompareQualityMetrics,
  extractCompareValuationMetrics,
} from "./compare-extract";
import { HEALTHY_LAYOUT_SIGNALS, type Claim, type ResearchReport, type Section } from "./schemas";

const SOURCE = {
  tool: "yfinance.fundamentals",
  fetched_at: "2026-05-04T14:00:00+00:00",
} as const;

function claim(description: string, value: number | string | null, history: { period: string; value: number }[] = []): Claim {
  return { description, value, source: { ...SOURCE }, history };
}

function section(title: string, claims: Claim[]): Section {
  return { title, summary: "", confidence: "high", claims };
}

function fakeReport(symbol: string, name: string, opts: Partial<{ sections: Section[] }> = {}): ResearchReport {
  return {
    symbol,
    name,
    sector: "semiconductors",
    generated_at: "2026-05-04T14:00:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
    layout_signals: HEALTHY_LAYOUT_SIGNALS,
    sections: opts.sections ?? [],
  };
}

describe("extractCompareHeroData", () => {
  it("returns name + sector + market cap from the report", () => {
    const report = fakeReport("NVDA", "NVIDIA Corporation", {
      sections: [
        section("Capital Allocation", [claim("Market capitalization", 2.19e12)]),
      ],
    });
    const hero = extractCompareHeroData(report);
    expect(hero.symbol).toBe("NVDA");
    expect(hero.name).toBe("NVIDIA Corporation");
    expect(hero.sector).toBe("semiconductors");
    expect(hero.marketCap).toBe(2.19e12);
  });

  it("nulls out market cap when claim is missing", () => {
    const report = fakeReport("NVDA", "NVIDIA Corporation", { sections: [] });
    expect(extractCompareHeroData(report).marketCap).toBeNull();
  });
});

describe("extractCompareValuationMetrics", () => {
  function valuation(values: { fwd?: number | null; ps?: number | null; ev?: number | null }): Section {
    const claims: Claim[] = [];
    if (values.fwd !== undefined && values.fwd !== null) {
      claims.push(claim("P/E ratio (forward, analyst consensus)", values.fwd));
    }
    if (values.ps !== undefined && values.ps !== null) {
      claims.push(claim("Price-to-sales ratio (trailing 12 months)", values.ps));
    }
    if (values.ev !== undefined && values.ev !== null) {
      claims.push(claim("Enterprise value to EBITDA", values.ev));
    }
    return section("Valuation", claims);
  }

  it("returns 3 cells in P/E FWD, P/S, EV/EBITDA order, all lowerIsBetter=true", () => {
    const a = fakeReport("NVDA", "NVIDIA", { sections: [valuation({ fwd: 32.1, ps: 24.4, ev: 41.2 })] });
    const b = fakeReport("AVGO", "Broadcom", { sections: [valuation({ fwd: 26.8, ps: 14.2, ev: 24.8 })] });
    const cells = extractCompareValuationMetrics(a, b);
    expect(cells).toHaveLength(3);
    expect(cells.map((c) => c.key)).toEqual(["forward_pe", "p_s", "ev_ebitda"]);
    expect(cells.every((c) => c.lowerIsBetter)).toBe(true);
    expect(cells[0]).toMatchObject({ valueA: 32.1, valueB: 26.8, label: "P/E FWD" });
    expect(cells[1]).toMatchObject({ valueA: 24.4, valueB: 14.2 });
  });

  it("nulls cell values when the underlying claim is missing", () => {
    const a = fakeReport("NVDA", "NVIDIA", { sections: [valuation({ fwd: 32.1 })] });
    const b = fakeReport("AVGO", "Broadcom", { sections: [valuation({})] });
    const cells = extractCompareValuationMetrics(a, b);
    expect(cells[0].valueA).toBe(32.1);
    expect(cells[0].valueB).toBeNull();
    expect(cells[1].valueA).toBeNull();
    expect(cells[1].valueB).toBeNull();
  });
});

describe("extractCompareQualityMetrics", () => {
  function quality(values: { gross?: number; op?: number; fcf?: number; roic?: number }): Section {
    const claims: Claim[] = [];
    if (values.gross !== undefined) claims.push(claim("Gross margin", values.gross));
    if (values.op !== undefined) claims.push(claim("Operating margin", values.op));
    if (values.fcf !== undefined) claims.push(claim("Free cash flow margin", values.fcf));
    if (values.roic !== undefined) claims.push(claim("Return on invested capital (TTM)", values.roic));
    return section("Quality", claims);
  }

  it("returns 4 cells (Gross, Op, FCF, ROIC) all lowerIsBetter=false", () => {
    const a = fakeReport("NVDA", "NVIDIA", { sections: [quality({ gross: 0.748, op: 0.612, fcf: 0.421, roic: 0.61 })] });
    const b = fakeReport("AVGO", "Broadcom", { sections: [quality({ gross: 0.738, op: 0.421, fcf: 0.412, roic: 0.21 })] });
    const cells = extractCompareQualityMetrics(a, b);
    expect(cells).toHaveLength(4);
    expect(cells.map((c) => c.key)).toEqual(["gross_margin", "operating_margin", "fcf_margin", "roic"]);
    expect(cells.every((c) => !c.lowerIsBetter)).toBe(true);
    expect(cells[0]).toMatchObject({ valueA: 0.748, valueB: 0.738 });
    expect(cells[3]).toMatchObject({ valueA: 0.61, valueB: 0.21 });
  });

  it("nulls cell value when claim is missing in either report", () => {
    const a = fakeReport("NVDA", "NVIDIA", { sections: [quality({ gross: 0.748 })] });
    const b = fakeReport("AVGO", "Broadcom", { sections: [quality({ gross: 0.738, op: 0.421 })] });
    const cells = extractCompareQualityMetrics(a, b);
    expect(cells[0]).toMatchObject({ valueA: 0.748, valueB: 0.738 });
    expect(cells[1].valueA).toBeNull();
    expect(cells[1].valueB).toBe(0.421);
  });
});

describe("extractCompareMarginOverlay", () => {
  function withOpMarginHistory(symbol: string, name: string, history: { period: string; value: number }[]): ResearchReport {
    return fakeReport(symbol, name, {
      sections: [
        section("Quality", [claim("Operating margin", history.at(-1)?.value ?? 0, history)]),
      ],
    });
  }

  it("returns 2 series labeled by ticker, with a / b accent colors", () => {
    const a = withOpMarginHistory("NVDA", "NVIDIA", [
      { period: "Q1-23", value: 0.32 },
      { period: "Q1-24", value: 0.55 },
    ]);
    const b = withOpMarginHistory("AVGO", "Broadcom", [
      { period: "Q1-23", value: 0.41 },
      { period: "Q1-24", value: 0.42 },
    ]);
    const series = extractCompareMarginOverlay(a, b);
    expect(series).toHaveLength(2);
    expect(series[0].label).toBe("NVDA");
    expect(series[0].color).toBe(COMPARE_COLOR_A);
    expect(series[1].label).toBe("AVGO");
    expect(series[1].color).toBe(COMPARE_COLOR_B);
    expect(series[0].history).toHaveLength(2);
  });

  it("drops a series whose Quality section or operating margin history is missing", () => {
    const a = withOpMarginHistory("NVDA", "NVIDIA", [
      { period: "Q1-23", value: 0.55 },
      { period: "Q1-24", value: 0.61 },
    ]);
    const b = fakeReport("AVGO", "Broadcom", { sections: [] });
    const series = extractCompareMarginOverlay(a, b);
    expect(series).toHaveLength(1);
    expect(series[0].label).toBe("NVDA");
  });
});

describe("extractCompareGrowthOverlay", () => {
  function withGrowthHistory(symbol: string, name: string, opts: { rev?: { period: string; value: number }[]; fcf?: { period: string; value: number }[] }): ResearchReport {
    const claims: Claim[] = [];
    if (opts.rev) claims.push(claim("Revenue per share", opts.rev.at(-1)?.value ?? 0, opts.rev));
    if (opts.fcf) claims.push(claim("Free cash flow per share", opts.fcf.at(-1)?.value ?? 0, opts.fcf));
    return fakeReport(symbol, name, { sections: [section("Quality", claims)] });
  }

  it("returns up to 4 rebased series (Rev × 2 + FCF × 2) — first point each = 100", () => {
    const a = withGrowthHistory("NVDA", "NVIDIA", {
      rev: [{ period: "2021", value: 5 }, { period: "2025", value: 31 }],
      fcf: [{ period: "2021", value: 2 }, { period: "2025", value: 24.4 }],
    });
    const b = withGrowthHistory("AVGO", "Broadcom", {
      rev: [{ period: "2021", value: 50 }, { period: "2025", value: 195 }],
      fcf: [{ period: "2021", value: 12 }, { period: "2025", value: 52.8 }],
    });
    const series = extractCompareGrowthOverlay(a, b);
    expect(series).toHaveLength(4);
    // Each series rebased so the first point is exactly 100.
    for (const s of series) {
      expect(s.history[0].value).toBeCloseTo(100, 5);
    }
    // Naming carries both ticker and metric (NVDA Rev, NVDA FCF, AVGO Rev, AVGO FCF).
    const labels = series.map((s) => s.label);
    expect(labels).toContain("NVDA Rev");
    expect(labels).toContain("NVDA FCF");
    expect(labels).toContain("AVGO Rev");
    expect(labels).toContain("AVGO FCF");
  });

  it("drops a series with empty history or zero-base first value", () => {
    const a = withGrowthHistory("NVDA", "NVIDIA", {
      rev: [{ period: "2021", value: 5 }, { period: "2025", value: 31 }],
      // No FCF history.
    });
    const b = withGrowthHistory("AVGO", "Broadcom", {
      // First point zero — can't rebase.
      rev: [{ period: "2021", value: 0 }, { period: "2025", value: 100 }],
      fcf: [{ period: "2021", value: 12 }, { period: "2025", value: 52.8 }],
    });
    const series = extractCompareGrowthOverlay(a, b);
    expect(series.map((s) => s.label).sort()).toEqual(["AVGO FCF", "NVDA Rev"]);
  });
});
