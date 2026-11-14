/**
 * valuation-history-extract — the Valuation section's year-end multiples
 * and today's reading against them (workstream B, 2026-11). Mirrors
 * app/services/valuation_history.py::DESCRIPTIONS and
 * research_derived.valuation_history_claims.
 */
import { describe, expect, it } from "vitest";

import { HEALTHY_LAYOUT_SIGNALS, type Claim, type ClaimValue, type ResearchReport } from "./schemas";
import { extractOwnHistory } from "./valuation-history-extract";

function claim(description: string, value: ClaimValue, years: number[] = []): Claim {
  return {
    description,
    value,
    source: { tool: "sec.xbrl", fetched_at: "2026-11-13T14:00:00+00:00" },
    history: years.map((v, i) => ({ period: String(2021 + i), value: v })),
  };
}

function report(valuationClaims: Claim[]): ResearchReport {
  return {
    symbol: "KO",
    generated_at: "2026-11-13T14:05:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
    thesis: null,
    name: null,
    sector: null,
    layout_signals: HEALTHY_LAYOUT_SIGNALS,
    sections: [{ title: "Valuation", summary: "", confidence: "high", claims: valuationClaims }],
  };
}

const FULL = [
  claim("P/E ratio (trailing 12 months)", 28),
  claim("Price-to-sales ratio (trailing 12 months)", 8),
  claim("P/E at fiscal year-end (SEC filings)", 18, [10, 12, 14, 16, 18]),
  claim("Price-to-sales at fiscal year-end (SEC filings)", 8, [4, 5, 6, 7, 8]),
  claim("Price-to-free-cash-flow at fiscal year-end (SEC filings)", 26, [20, 22, 25, 30, 26]),
  claim("Price-to-free-cash-flow (trailing 12 months)", 27.5),
  claim("Median P/E across 5 fiscal year-ends (2021–2025)", 14),
  claim("Trailing P/E vs its own median of 14.00 across 5 fiscal year-ends: premium (+) or discount (−)", 1.0),
  claim("Median price-to-sales across 5 fiscal year-ends (2021–2025)", 6),
  claim(
    "Price-to-sales vs its own median of 6.00 across 5 fiscal year-ends: premium (+) or discount (−)",
    0.3333,
  ),
  claim("Median price-to-free-cash-flow across 5 fiscal year-ends (2021–2025)", 25),
  claim(
    "Price-to-free-cash-flow vs its own median of 25.00 across 5 fiscal year-ends: premium (+) or discount (−)",
    0.1,
  ),
];

describe("extractOwnHistory", () => {
  it("returns one panel per multiple, in P/E, P/S, P/FCF order", () => {
    const panels = extractOwnHistory(report(FULL));
    expect(panels.map((p) => p.key)).toEqual(["pe", "ps", "pfcf"]);
    expect(panels.map((p) => p.label)).toEqual(["P/E", "Price / sales", "Price / free cash flow"]);
  });

  it("carries the year-end points, the median, today and the gap to the median", () => {
    const [pe] = extractOwnHistory(report(FULL));
    expect(pe.history.map((p) => p.period)).toEqual(["2021", "2022", "2023", "2024", "2025"]);
    expect(pe.history.map((p) => p.value)).toEqual([10, 12, 14, 16, 18]);
    expect(pe.median).toBe(14);
    expect(pe.today).toBe(28);
    expect(pe.premium).toBe(1.0);
  });

  it("reads the descriptions that name today's figure and the direction (report version 7)", () => {
    // 2026-11-14: the comparison line now carries today's figure and says
    // above or below in words; the median line says it is not today's.
    const v7 = FULL.map((c) =>
      c.description.startsWith("Median")
        ? { ...c, description: `${c.description}: the company's own norm, not today's multiple` }
        : c.description.startsWith("Price-to-sales vs its own median")
          ? {
              ...c,
              description:
                "Price-to-sales vs its own median of 6.00 across 5 fiscal year-ends (2021–2025): " +
                "today 8.00, above the median by",
            }
          : c,
    );
    const ps = extractOwnHistory(report(v7))[1];
    expect(ps.median).toBe(6);
    expect(ps.premium).toBe(0.3333);
  });

  it("reads today's price-to-free-cash-flow from its derived claim", () => {
    const pfcf = extractOwnHistory(report(FULL))[2];
    expect(pfcf.today).toBe(27.5);
    expect(pfcf.median).toBe(25);
  });

  it("keeps a panel whose history is too short for a median, without one", () => {
    // RIVN: four year-ends of price-to-sales, no earnings at all.
    const panels = extractOwnHistory(
      report([
        claim("Price-to-sales ratio (trailing 12 months)", 4.1),
        claim("Price-to-sales at fiscal year-end (SEC filings)", 4.3, [10.1, 5.0, 2.7, 4.3]),
      ]),
    );
    expect(panels.map((p) => p.key)).toEqual(["ps"]);
    expect(panels[0].median).toBeNull();
    expect(panels[0].premium).toBeNull();
    expect(panels[0].today).toBe(4.1);
  });

  it("drops a multiple with fewer than two year-ends", () => {
    const panels = extractOwnHistory(report([claim("P/E at fiscal year-end (SEC filings)", 18, [18])]));
    expect(panels).toEqual([]);
  });

  it("returns nothing for a report built before the year-end multiples", () => {
    expect(extractOwnHistory(report([claim("P/E ratio (trailing 12 months)", 28)]))).toEqual([]);
    expect(extractOwnHistory({ ...report([]), sections: [] })).toEqual([]);
  });

  it("treats a missing or non-numeric today as absent", () => {
    const panels = extractOwnHistory(
      report([
        claim("P/E ratio (trailing 12 months)", null),
        claim("P/E at fiscal year-end (SEC filings)", 18, [10, 12, 14, 16, 18]),
      ]),
    );
    expect(panels[0].today).toBeNull();
  });
});
