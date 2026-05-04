/**
 * peer-grouping tests (Phase 3.3.C).
 *
 * Two pure functions are pinned here:
 *
 * 1. ``groupPeers(claims)`` — flat ``Claim[]`` → ``PeerRow[]``.
 *    Parses descriptions of the form ``"<TICKER>: <metric_desc>"``
 *    emitted by ``app/services/peers.py``, groups by ticker, returns
 *    one row per peer with ``pe`` (trailing P/E) and ``margin`` (gross
 *    margin) when both are numeric.
 *
 * 2. ``extractSubject(report)`` — for the report's symbol, look up
 *    ``"P/E ratio (trailing 12 months)"`` in the Valuation section
 *    and ``"Gross margin"`` in the Quality section. Returns null when
 *    either is missing (e.g. EARNINGS focus mode skips Quality).
 *
 * 3. ``extractMedian(claims)`` — pulls the per-metric medians out of
 *    the same claims list (descriptions like
 *    ``"Peer median: P/E ratio (trailing 12 months)"``). Used to draw
 *    a faint reference dot on the scatter.
 *
 * The descriptions tested here are copy-pasted from
 * ``app/services/peers.py::_DESCRIPTIONS`` and
 * ``app/services/fundamentals.py::_DESCRIPTIONS``; a backend rename
 * fails these tests rather than silently breaking the chart.
 */
import { describe, expect, it } from "vitest";

import {
  HEALTHY_LAYOUT_SIGNALS,
  type Claim,
  type ClaimValue,
  type ResearchReport,
  type Section,
} from "./schemas";
import { extractMedian, extractSubject, groupPeers } from "./peer-grouping";

// ── helpers ──────────────────────────────────────────────────────────

function claim(description: string, value: ClaimValue): Claim {
  return {
    description,
    value,
    source: {
      tool: "yfinance.peers",
      fetched_at: "2026-04-29T14:00:00+00:00",
    },
    history: [],
  };
}

function section(title: string, claims: Claim[]): Section {
  return { title, claims, summary: "", confidence: "high" };
}

function peerClaims(
  symbol: string,
  pe: ClaimValue,
  margin: ClaimValue,
  ps: ClaimValue = null,
  evEbitda: ClaimValue = null,
): Claim[] {
  return [
    claim(`${symbol}: P/E ratio (trailing 12 months)`, pe),
    claim(`${symbol}: Price-to-sales ratio (trailing 12 months)`, ps),
    claim(`${symbol}: Enterprise value to EBITDA`, evEbitda),
    claim(`${symbol}: Gross margin`, margin),
  ];
}

// ── groupPeers ───────────────────────────────────────────────────────

describe("groupPeers", () => {
  it("groups flat per-peer claims into one row per peer", () => {
    const claims = [
      ...peerClaims("AMD", 25.4, 0.46),
      ...peerClaims("INTC", 18.2, 0.41),
      ...peerClaims("QCOM", 14.8, 0.55),
    ];
    const rows = groupPeers(claims);
    expect(rows).toHaveLength(3);
    expect(rows.map((r) => r.symbol).sort()).toEqual(["AMD", "INTC", "QCOM"]);
    expect(rows.find((r) => r.symbol === "AMD")).toEqual({
      symbol: "AMD",
      pe: 25.4,
      margin: 0.46,
    });
  });

  it("drops a peer that's missing P/E", () => {
    const claims = [
      ...peerClaims("AMD", null, 0.46), // P/E missing
      ...peerClaims("INTC", 18.2, 0.41),
    ];
    const rows = groupPeers(claims);
    expect(rows).toHaveLength(1);
    expect(rows[0].symbol).toBe("INTC");
  });

  it("drops a peer that's missing gross margin", () => {
    const claims = [
      ...peerClaims("AMD", 25.4, null),
      ...peerClaims("INTC", 18.2, 0.41),
    ];
    const rows = groupPeers(claims);
    expect(rows).toHaveLength(1);
    expect(rows[0].symbol).toBe("INTC");
  });

  it("ignores median.* claims (they're aggregates, not peers)", () => {
    const claims = [
      ...peerClaims("AMD", 25.4, 0.46),
      claim("Peer median: P/E ratio (trailing 12 months)", 22.0),
      claim("Peer median: Gross margin", 0.48),
    ];
    const rows = groupPeers(claims);
    expect(rows).toHaveLength(1);
    expect(rows[0].symbol).toBe("AMD");
  });

  it("ignores sector and peers_list metadata claims", () => {
    const claims = [
      claim("Resolved sector for peer comparison", "semiconductors"),
      claim("Peers selected for comparison", "AMD, INTC, QCOM"),
      ...peerClaims("AMD", 25.4, 0.46),
    ];
    const rows = groupPeers(claims);
    expect(rows.map((r) => r.symbol)).toEqual(["AMD"]);
  });

  it("returns an empty list when no peer has both P/E and gross margin", () => {
    const claims = [
      ...peerClaims("AMD", null, null),
      ...peerClaims("INTC", null, null),
    ];
    expect(groupPeers(claims)).toEqual([]);
  });

  it("ignores P/S and EV/EBITDA claims (not on the scatter axes)", () => {
    // Anti-regression: only the two scatter-axis metrics matter; the
    // other two PEER_METRICS claims must not become rows of their own.
    const claims = [
      claim("AMD: Price-to-sales ratio (trailing 12 months)", 5.2),
      claim("AMD: Enterprise value to EBITDA", 12.0),
      ...peerClaims("AMD", 25.4, 0.46),
    ];
    const rows = groupPeers(claims);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toEqual({ symbol: "AMD", pe: 25.4, margin: 0.46 });
  });

  it("does not treat non-numeric values as plottable", () => {
    const claims = [
      claim("AMD: P/E ratio (trailing 12 months)", "n/a" as unknown as number),
      claim("AMD: Gross margin", true as unknown as number),
    ];
    expect(groupPeers(claims)).toEqual([]);
  });
});

// ── extractMedian ────────────────────────────────────────────────────

describe("extractMedian", () => {
  it("pulls the median P/E and median gross margin", () => {
    const claims = [
      claim("Peer median: P/E ratio (trailing 12 months)", 22.0),
      claim("Peer median: Gross margin", 0.48),
      claim("Peer median: Price-to-sales ratio (trailing 12 months)", 6.5),
    ];
    expect(extractMedian(claims)).toEqual({ pe: 22.0, margin: 0.48 });
  });

  it("returns null when either median is missing", () => {
    expect(
      extractMedian([
        claim("Peer median: P/E ratio (trailing 12 months)", 22.0),
        // gross margin median absent
      ]),
    ).toBeNull();
  });

  it("returns null when either median is non-numeric", () => {
    expect(
      extractMedian([
        claim("Peer median: P/E ratio (trailing 12 months)", null),
        claim("Peer median: Gross margin", 0.48),
      ]),
    ).toBeNull();
  });
});

// ── extractSubject ───────────────────────────────────────────────────

function buildReport(opts: {
  symbol?: string;
  hasValuation?: boolean;
  hasQuality?: boolean;
  pe?: ClaimValue;
  margin?: ClaimValue;
  extraValuationClaims?: Claim[];
  extraQualityClaims?: Claim[];
} = {}): ResearchReport {
  const sections: Section[] = [];
  // Use ``"pe" in opts`` to distinguish "explicitly null" from "not
  // specified" — the ?? operator collapses both to the default which
  // hides the null-value test cases.
  const pe = "pe" in opts ? opts.pe : 28.5;
  const margin = "margin" in opts ? opts.margin : 0.46;
  if (opts.hasValuation !== false) {
    sections.push(
      section("Valuation", [
        claim("P/E ratio (trailing 12 months)", pe ?? null),
        ...(opts.extraValuationClaims ?? []),
      ]),
    );
  }
  if (opts.hasQuality !== false) {
    sections.push(
      section("Quality", [
        claim("Gross margin", margin ?? null),
        ...(opts.extraQualityClaims ?? []),
      ]),
    );
  }
  sections.push(section("Peers", []));
  return {
    symbol: opts.symbol ?? "AAPL",
    generated_at: "2026-04-29T14:05:00+00:00",
    overall_confidence: "high",
    tool_calls_audit: [],
    name: null,
    sector: null,
    layout_signals: HEALTHY_LAYOUT_SIGNALS,
    sections,
  };
}

describe("extractSubject", () => {
  it("returns subject {symbol, pe, margin} when both sections are present", () => {
    const report = buildReport({ symbol: "AAPL", pe: 28.5, margin: 0.46 });
    expect(extractSubject(report)).toEqual({
      symbol: "AAPL",
      pe: 28.5,
      margin: 0.46,
    });
  });

  it("returns null when Quality section is absent (e.g. EARNINGS focus mode)", () => {
    expect(extractSubject(buildReport({ hasQuality: false }))).toBeNull();
  });

  it("returns null when Valuation section is absent", () => {
    expect(extractSubject(buildReport({ hasValuation: false }))).toBeNull();
  });

  it("returns null when subject P/E is null (data unavailable)", () => {
    expect(extractSubject(buildReport({ pe: null }))).toBeNull();
  });

  it("returns null when subject gross margin is null", () => {
    expect(extractSubject(buildReport({ margin: null }))).toBeNull();
  });

  it("matches descriptions exactly (does not pick up gross_margin_trend_1y)", () => {
    // Quality section also has 'Gross margin, year-over-year change'
    // — must not match.
    const report = buildReport({
      extraQualityClaims: [
        claim("Gross margin, year-over-year change", 0.02),
      ],
    });
    expect(extractSubject(report)?.margin).toBe(0.46);
  });
});
