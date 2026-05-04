/**
 * valuation-extract tests (Phase 4.2).
 *
 * Pure helpers that pull ValuationCard's data from the Valuation
 * section + Peers section of a ResearchReport. The extract is a
 * cross-section join — subject values come from Valuation
 * (``trailing_pe``, ``forward_pe``, ``p_s``, ``ev_ebitda``), and
 * peer distribution comes from Peers (``<TICKER>: <metric>`` and
 * ``Peer median: <metric>`` claims).
 *
 * Returned shape per cell:
 *   {
 *     metric: "trailing_pe",
 *     subject: 28.5 | null,
 *     peerMedian: 22.0 | null,
 *     peerMin: 12.0 | null,
 *     peerMax: 38.5 | null,
 *     percentile: 0.66 | null,  // subject's rank within peers' values
 *   }
 *
 * Percentile is computed as `count(peer_value <= subject) / peer_count`
 * — when subject is missing, percentile is null. When the peer set has
 * < 2 values, percentile is null (rank is meaningless).
 */
import { describe, expect, it } from "vitest";

import { extractValuationCells } from "./valuation-extract";
import {
  HEALTHY_LAYOUT_SIGNALS,
  type Claim,
  type ClaimValue,
  type ResearchReport,
  type Section,
} from "./schemas";

function claim(description: string, value: ClaimValue): Claim {
  return {
    description,
    value,
    source: { tool: "yfinance", fetched_at: "2026-05-03T14:00:00+00:00" },
    history: [],
  };
}

function section(title: string, claims: Claim[]): Section {
  return { title, claims, summary: "", confidence: "high" };
}

function buildReport(opts: {
  symbol?: string;
  valuationClaims?: Claim[];
  peersClaims?: Claim[];
} = {}): ResearchReport {
  return {
    symbol: opts.symbol ?? "NVDA",
    generated_at: "2026-05-03T14:00:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
    name: null,
    sector: null,
    layout_signals: HEALTHY_LAYOUT_SIGNALS,
    sections: [
      section("Valuation", opts.valuationClaims ?? []),
      section("Peers", opts.peersClaims ?? []),
    ],
  };
}

// Helper for peers claims
function peerMetric(symbol: string, metric: string, value: ClaimValue): Claim {
  return claim(`${symbol}: ${metric}`, value);
}

function median(metric: string, value: ClaimValue): Claim {
  return claim(`Peer median: ${metric}`, value);
}

const PE = "P/E ratio (trailing 12 months)";
const FWD_PE = "P/E ratio (forward, analyst consensus)";
const PS = "Price-to-sales ratio (trailing 12 months)";
const EVE = "Enterprise value to EBITDA";
const GM = "Gross margin";

describe("extractValuationCells", () => {
  it("returns 4 cells: trailing P/E, forward P/E, P/S, EV/EBITDA", () => {
    const cells = extractValuationCells(buildReport());
    expect(cells.map((c) => c.metric)).toEqual([
      "trailing_pe",
      "forward_pe",
      "p_s",
      "ev_ebitda",
    ]);
  });

  it("populates subject from the Valuation section", () => {
    const report = buildReport({
      valuationClaims: [
        claim(PE, 28.5),
        claim(FWD_PE, 24.1),
        claim(PS, 18.0),
        claim(EVE, 22.4),
      ],
    });
    const cells = extractValuationCells(report);
    expect(cells.find((c) => c.metric === "trailing_pe")?.subject).toBe(28.5);
    expect(cells.find((c) => c.metric === "forward_pe")?.subject).toBe(24.1);
    expect(cells.find((c) => c.metric === "p_s")?.subject).toBe(18.0);
    expect(cells.find((c) => c.metric === "ev_ebitda")?.subject).toBe(22.4);
  });

  it("populates peer median + peer min/max from the Peers section", () => {
    const report = buildReport({
      valuationClaims: [claim(PE, 28.5)],
      peersClaims: [
        peerMetric("AMD", PE, 25.4),
        peerMetric("INTC", PE, 18.2),
        peerMetric("QCOM", PE, 14.8),
        peerMetric("AVGO", PE, 38.5),
        median(PE, 22.0),
        // Other metrics also present (different cell) — should be ignored.
        peerMetric("AMD", GM, 0.46),
      ],
    });
    const peCell = extractValuationCells(report).find(
      (c) => c.metric === "trailing_pe",
    );
    expect(peCell?.peerMedian).toBe(22.0);
    expect(peCell?.peerMin).toBe(14.8);
    expect(peCell?.peerMax).toBe(38.5);
  });

  it("computes percentile as the subject's rank within peer values", () => {
    const report = buildReport({
      valuationClaims: [claim(PE, 30.0)],
      peersClaims: [
        peerMetric("AMD", PE, 10.0),
        peerMetric("INTC", PE, 20.0),
        peerMetric("QCOM", PE, 40.0),
        peerMetric("AVGO", PE, 50.0),
        median(PE, 30.0),
      ],
    });
    const peCell = extractValuationCells(report).find(
      (c) => c.metric === "trailing_pe",
    );
    // Subject 30.0 vs peer values [10, 20, 40, 50]: 2 of 4 peers <=
    // subject ⇒ percentile = 0.5.
    expect(peCell?.percentile).toBe(0.5);
  });

  it("returns null percentile when subject is missing", () => {
    const report = buildReport({
      valuationClaims: [], // no subject value
      peersClaims: [
        peerMetric("AMD", PE, 25.4),
        peerMetric("INTC", PE, 18.2),
        median(PE, 22.0),
      ],
    });
    const peCell = extractValuationCells(report).find(
      (c) => c.metric === "trailing_pe",
    );
    expect(peCell?.subject).toBeNull();
    expect(peCell?.percentile).toBeNull();
  });

  it("returns null percentile when peer set has < 2 values", () => {
    const report = buildReport({
      valuationClaims: [claim(PE, 28.5)],
      peersClaims: [peerMetric("AMD", PE, 25.4), median(PE, 25.4)],
    });
    const peCell = extractValuationCells(report).find(
      (c) => c.metric === "trailing_pe",
    );
    expect(peCell?.subject).toBe(28.5);
    expect(peCell?.percentile).toBeNull();
  });

  it("returns null fields when sections are absent", () => {
    const report: ResearchReport = {
      symbol: "NVDA",
      generated_at: "2026-05-03T14:00:00+00:00",
      overall_confidence: "high",
      tool_calls_audit: [],
      name: null,
      sector: null,
      layout_signals: HEALTHY_LAYOUT_SIGNALS,
      sections: [],
    };
    const cells = extractValuationCells(report);
    expect(cells).toHaveLength(4);
    cells.forEach((c) => {
      expect(c.subject).toBeNull();
      expect(c.peerMedian).toBeNull();
      expect(c.peerMin).toBeNull();
      expect(c.peerMax).toBeNull();
      expect(c.percentile).toBeNull();
    });
  });

  it("ignores non-numeric claim values in the peer distribution", () => {
    const report = buildReport({
      valuationClaims: [claim(PE, 28.5)],
      peersClaims: [
        peerMetric("AMD", PE, 25.4),
        peerMetric("INTC", PE, null),
        peerMetric("QCOM", PE, "n/a" as unknown as number),
        peerMetric("AVGO", PE, 38.5),
        median(PE, 22.0),
      ],
    });
    const peCell = extractValuationCells(report).find(
      (c) => c.metric === "trailing_pe",
    );
    // Only AMD + AVGO numeric; min/max derived from those two.
    expect(peCell?.peerMin).toBe(25.4);
    expect(peCell?.peerMax).toBe(38.5);
  });
});
