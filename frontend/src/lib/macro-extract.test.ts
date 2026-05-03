/**
 * macro-extract tests (Phase 4.3.A).
 *
 * Pulls per-FRED-series panels out of the Macro section. The backend
 * emits 3 claims per series:
 *
 *   "{label} (latest observation)"   ← value-bearing, history-bearing
 *   "{label} observation date"       ← string value, no history
 *   "Human-readable label for FRED series {id}"  ← static metadata
 *
 * Plus 2 metadata claims at the section root:
 *
 *   "Resolved sector for macro context"
 *   "FRED series chosen for this sector"
 *
 * For each known series we return a panel:
 *
 *   { id, label, latest, units, history, observationDate }
 *
 * The panel renders as one mini area-chart in MacroPanel. Series with
 * no value or no history are skipped; the remaining panels render in
 * the sector's canonical order.
 */
import { describe, expect, it } from "vitest";

import { extractMacroPanels } from "./macro-extract";
import type { Claim, ClaimHistoryPoint, ClaimValue, Section } from "./schemas";

function claim(
  description: string,
  value: ClaimValue,
  history: ClaimHistoryPoint[] = [],
): Claim {
  return {
    description,
    value,
    source: { tool: "fred.macro", fetched_at: "2026-05-03T14:00:00+00:00" },
    history,
  };
}

function section(claims: Claim[]): Section {
  return { title: "Macro", claims, summary: "", confidence: "high" };
}

const CPI_HIST: ClaimHistoryPoint[] = [
  { period: "2024-01", value: 3.4 },
  { period: "2024-02", value: 3.2 },
  { period: "2024-03", value: 3.0 },
  { period: "2024-04", value: 2.8 },
];

const RATE_HIST: ClaimHistoryPoint[] = [
  { period: "2024-01", value: 4.5 },
  { period: "2024-02", value: 4.3 },
  { period: "2024-03", value: 4.2 },
  { period: "2024-04", value: 4.1 },
];

describe("extractMacroPanels", () => {
  it("returns one panel per FRED series with full data", () => {
    const s = section([
      claim("Resolved sector for macro context", "megacap_tech"),
      claim("FRED series chosen for this sector", "DGS10"),
      claim("10Y Treasury yield (latest observation)", 4.1, RATE_HIST),
      claim("10Y Treasury yield observation date", "2024-04-01"),
      claim("Human-readable label for FRED series DGS10", "10Y Treasury yield"),
      claim("Consumer price index (latest observation)", 2.8, CPI_HIST),
      claim("Consumer price index observation date", "2024-04-01"),
      claim(
        "Human-readable label for FRED series CPIAUCSL",
        "Consumer price index",
      ),
    ]);
    const panels = extractMacroPanels(s);
    expect(panels).toHaveLength(2);
    expect(panels.map((p) => p.label).sort()).toEqual([
      "10Y Treasury yield",
      "Consumer price index",
    ]);
  });

  it("populates each panel with latest, history, and observation date", () => {
    const s = section([
      claim("10Y Treasury yield (latest observation)", 4.1, RATE_HIST),
      claim("10Y Treasury yield observation date", "2024-04-01"),
    ]);
    const panel = extractMacroPanels(s)[0];
    expect(panel.latest).toBe(4.1);
    expect(panel.history).toHaveLength(4);
    expect(panel.observationDate).toBe("2024-04-01");
  });

  it("skips a series whose latest value is non-numeric", () => {
    const s = section([
      claim("10Y Treasury yield (latest observation)", null, RATE_HIST),
      claim("Consumer price index (latest observation)", 2.8, CPI_HIST),
    ]);
    const panels = extractMacroPanels(s);
    expect(panels.map((p) => p.label)).toEqual(["Consumer price index"]);
  });

  it("skips a series whose history is empty", () => {
    const s = section([
      claim("10Y Treasury yield (latest observation)", 4.1, []),
      claim("Consumer price index (latest observation)", 2.8, CPI_HIST),
    ]);
    const panels = extractMacroPanels(s);
    expect(panels.map((p) => p.label)).toEqual(["Consumer price index"]);
  });

  it("returns an empty list when section has no usable data claims", () => {
    expect(
      extractMacroPanels(
        section([
          claim("Resolved sector for macro context", "unknown"),
          claim("FRED series chosen for this sector", "—"),
        ]),
      ),
    ).toEqual([]);
  });

  it("ignores metadata claims (sector / series_list)", () => {
    const s = section([
      claim("Resolved sector for macro context", "megacap_tech"),
      claim("FRED series chosen for this sector", "DGS10"),
      claim("10Y Treasury yield (latest observation)", 4.1, RATE_HIST),
    ]);
    const panels = extractMacroPanels(s);
    expect(panels).toHaveLength(1);
    expect(panels[0].label).toBe("10Y Treasury yield");
  });
});
