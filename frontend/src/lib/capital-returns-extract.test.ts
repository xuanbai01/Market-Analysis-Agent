import { describe, expect, it } from "vitest";

import { DESC, extractCapitalReturns, hasCapitalReturns } from "./capital-returns-extract";
import type { Claim, Section } from "./schemas";

const SRC = { tool: "computed.analytics", fetched_at: "2026-11-09T00:00:00+00:00" };

function claim(description: string, value: number | null, unit: Claim["unit"]): Claim {
  return { description, value, unit, source: SRC, history: [] };
}

function section(claims: Claim[]): Section {
  return { title: "Capital Allocation", claims, summary: "", confidence: "high", card_narrative: null };
}

describe("extractCapitalReturns", () => {
  it("reads yields, stats and context in display units", () => {
    const r = extractCapitalReturns(
      section([
        claim(DESC.shareholderYield, 0.024, "fraction"),
        claim(DESC.dividendYield, 2.22, "percent"),
        claim(DESC.buybackYield, 0.0018, "fraction"),
        claim(DESC.payout, 0.6265, "fraction"),
        claim(DESC.coverage, 1.5577, "ratio"),
        claim(DESC.marketCap, 411.56e9, "usd"),
        claim(DESC.shortDays, 3.06, "ratio"),
      ]),
    );
    expect(r.shareholderYield).toBe("2.40%");
    expect(r.dividendYield).toBe("2.22%");
    expect(r.buybackYield).toBe("0.18%");
    expect(r.stats).toEqual([
      { label: "Payout ratio", value: "62.65%", description: DESC.payout },
      { label: "FCF covers dividend", value: "1.56×", description: DESC.coverage },
    ]);
    expect(r.marketCap).toBe("$411.56B");
    expect(r.shortDays).toBe("3.1 days");
  });

  it("skips claims that are missing or empty", () => {
    const r = extractCapitalReturns(section([claim(DESC.payout, null, "fraction")]));
    expect(r.stats).toEqual([]);
    expect(r.shareholderYield).toBeNull();
  });

  it("treats a zero dividend yield as no dividend, not '0.00% dividend'", () => {
    const r = extractCapitalReturns(section([claim(DESC.dividendYield, 0, "percent")]));
    expect(r.dividendYield).toBeNull();
    expect(r.paysDividend).toBe(false);
    expect(extractCapitalReturns(section([])).paysDividend).toBeNull();
  });

  it("says whether there is anything to show", () => {
    expect(hasCapitalReturns(undefined)).toBe(false);
    expect(hasCapitalReturns(section([claim(DESC.marketCap, 1e9, "usd")]))).toBe(false);
    expect(hasCapitalReturns(section([claim(DESC.dividendYield, 2.2, "percent")]))).toBe(true);
  });
});
