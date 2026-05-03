/**
 * hero-extract tests (Phase 4.1).
 *
 * Pure function that pulls the data the HeroCard needs out of a
 * ResearchReport. Like featured-claim.ts (3.3.B) and peer-grouping.ts
 * (3.3.C), it matches by claim description rather than key — the
 * backend keys don't survive the schema flatten.
 *
 * Tests pin: realistic descriptions resolve, missing data returns
 * null fields, hero-card-relevant fields surfaced cleanly.
 */
import { describe, expect, it } from "vitest";

import { extractHeroData } from "./hero-extract";
import type { Claim, ClaimValue, ResearchReport, Section } from "./schemas";

function claim(description: string, value: ClaimValue): Claim {
  return {
    description,
    value,
    source: {
      tool: "yfinance.fundamentals",
      fetched_at: "2026-05-02T14:00:00+00:00",
    },
    history: [],
  };
}

function section(title: string, claims: Claim[]): Section {
  return { title, claims, summary: "", confidence: "high" };
}

function report(opts: {
  name?: string | null;
  sector?: string | null;
  valuationClaims?: Claim[];
  qualityClaims?: Claim[];
  capAllocClaims?: Claim[];
} = {}): ResearchReport {
  return {
    symbol: "NVDA",
    generated_at: "2026-05-02T14:00:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
    name: "name" in opts ? opts.name : "NVIDIA Corporation",
    sector: "sector" in opts ? opts.sector : "megacap_tech",
    sections: [
      section("Valuation", opts.valuationClaims ?? []),
      section("Quality", opts.qualityClaims ?? []),
      section("Capital Allocation", opts.capAllocClaims ?? []),
    ],
  };
}

describe("extractHeroData", () => {
  it("pulls name + sector from top-level fields", () => {
    const data = extractHeroData(report());
    expect(data?.name).toBe("NVIDIA Corporation");
    expect(data?.sector).toBe("megacap_tech");
  });

  it("pulls 52W high/low from Valuation/Quality/CapAlloc claims", () => {
    const data = extractHeroData(
      report({
        capAllocClaims: [
          claim("52-week high", 921.04),
          claim("52-week low", 410.18),
          claim("Market capitalization", 4.0e12),
        ],
      }),
    );
    expect(data?.fiftyTwoWeekHigh).toBe(921.04);
    expect(data?.fiftyTwoWeekLow).toBe(410.18);
    expect(data?.marketCap).toBe(4.0e12);
  });

  it("pulls Forward P/E from Valuation section", () => {
    const data = extractHeroData(
      report({
        valuationClaims: [
          claim("P/E ratio (forward, analyst consensus)", 32.1),
        ],
      }),
    );
    expect(data?.forwardPE?.value).toBe(32.1);
  });

  it("pulls ROIC TTM from Quality section", () => {
    const data = extractHeroData(
      report({
        qualityClaims: [
          claim("Return on invested capital (TTM)", 0.61),
        ],
      }),
    );
    expect(data?.roicTTM).toBe(0.61);
  });

  it("pulls FCF margin from Quality section", () => {
    const data = extractHeroData(
      report({
        qualityClaims: [claim("Free cash flow margin", 0.421)],
      }),
    );
    expect(data?.fcfMargin).toBe(0.421);
  });

  it("returns null for fields that aren't found", () => {
    const data = extractHeroData(
      report({
        valuationClaims: [],
        qualityClaims: [],
        capAllocClaims: [],
      }),
    );
    // Top-level metadata still present
    expect(data?.name).toBe("NVIDIA Corporation");
    // Per-claim fields are null
    expect(data?.forwardPE).toBeNull();
    expect(data?.roicTTM).toBeNull();
    expect(data?.fcfMargin).toBeNull();
    expect(data?.marketCap).toBeNull();
    expect(data?.fiftyTwoWeekHigh).toBeNull();
    expect(data?.fiftyTwoWeekLow).toBeNull();
  });

  it("returns null fields when name/sector are absent (pre-4.1 cached report)", () => {
    const data = extractHeroData(report({ name: null, sector: null }));
    expect(data?.name).toBeNull();
    expect(data?.sector).toBeNull();
  });

  it("rejects non-numeric values for numeric fields", () => {
    const data = extractHeroData(
      report({
        valuationClaims: [
          claim("P/E ratio (forward, analyst consensus)", null),
        ],
      }),
    );
    expect(data?.forwardPE).toBeNull();
  });
});
