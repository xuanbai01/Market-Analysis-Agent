/**
 * peer-grouping axis-pair tests (Phase 4.2).
 *
 * The original (3.3.C) helpers grouped peers around a fixed
 * (P/E, gross margin) pair for the Recharts ScatterChart. PeerScatterV2
 * needs the same shape but pivotable across the 4 PEER_METRICS, so
 * 4.2 adds two generic helpers that take metric descriptions as
 * arguments:
 *
 *   - groupPeersForAxes(claims, xMetric, yMetric) → PeerRow[]
 *   - extractMedianForAxes(claims, xMetric, yMetric) → MedianPoint | null
 *
 * The original groupPeers / extractMedian re-implement themselves on
 * top of these (see peer-grouping.ts). Tests pin both new helpers and
 * confirm the legacy callers still work.
 */
import { describe, expect, it } from "vitest";

import {
  extractMedianForAxes,
  groupPeers,
  groupPeersForAxes,
} from "./peer-grouping";
import type { Claim, ClaimValue } from "./schemas";

const PE = "P/E ratio (trailing 12 months)";
const PS = "Price-to-sales ratio (trailing 12 months)";
const EV = "Enterprise value to EBITDA";
const GM = "Gross margin";

function claim(description: string, value: ClaimValue): Claim {
  return {
    description,
    value,
    source: { tool: "yfinance.peers", fetched_at: "2026-05-03T14:00:00+00:00" },
    history: [],
  };
}

function peerClaims(
  symbol: string,
  values: { pe?: ClaimValue; ps?: ClaimValue; ev?: ClaimValue; gm?: ClaimValue },
): Claim[] {
  const out: Claim[] = [];
  if (values.pe !== undefined) out.push(claim(`${symbol}: ${PE}`, values.pe));
  if (values.ps !== undefined) out.push(claim(`${symbol}: ${PS}`, values.ps));
  if (values.ev !== undefined) out.push(claim(`${symbol}: ${EV}`, values.ev));
  if (values.gm !== undefined) out.push(claim(`${symbol}: ${GM}`, values.gm));
  return out;
}

// ── groupPeersForAxes ────────────────────────────────────────────────

describe("groupPeersForAxes", () => {
  it("groups peers by an arbitrary (xMetric, yMetric) pair", () => {
    const claims = [
      ...peerClaims("AMD", { ps: 5.2, gm: 0.46 }),
      ...peerClaims("INTC", { ps: 2.4, gm: 0.41 }),
      ...peerClaims("QCOM", { ps: 4.1, gm: 0.55 }),
    ];
    const rows = groupPeersForAxes(claims, PS, GM);
    expect(rows).toHaveLength(3);
    expect(rows.find((r) => r.symbol === "AMD")).toEqual({
      symbol: "AMD",
      x: 5.2,
      y: 0.46,
    });
  });

  it("supports EV/EBITDA × Gross Margin", () => {
    const claims = [
      ...peerClaims("AMD", { ev: 22.0, gm: 0.46 }),
      ...peerClaims("INTC", { ev: 14.0, gm: 0.41 }),
    ];
    const rows = groupPeersForAxes(claims, EV, GM);
    expect(rows).toHaveLength(2);
    expect(rows.find((r) => r.symbol === "AMD")?.x).toBe(22.0);
  });

  it("drops peers missing either axis metric", () => {
    const claims = [
      ...peerClaims("AMD", { ps: 5.2, gm: 0.46 }),
      ...peerClaims("INTC", { ps: 2.4 /* gm missing */ }),
      ...peerClaims("QCOM", { /* ps missing */ gm: 0.55 }),
    ];
    const rows = groupPeersForAxes(claims, PS, GM);
    expect(rows.map((r) => r.symbol)).toEqual(["AMD"]);
  });

  it("ignores Peer median:* and other metadata", () => {
    const claims = [
      ...peerClaims("AMD", { pe: 25.4, gm: 0.46 }),
      claim(`Peer median: ${PE}`, 22.0),
      claim(`Peer median: ${GM}`, 0.48),
      claim("Resolved sector for peer comparison", "semiconductors"),
    ];
    const rows = groupPeersForAxes(claims, PE, GM);
    expect(rows.map((r) => r.symbol)).toEqual(["AMD"]);
  });

  it("rejects non-numeric values", () => {
    const claims = [
      ...peerClaims("AMD", {
        pe: "n/a" as unknown as number,
        gm: 0.46,
      }),
      ...peerClaims("INTC", { pe: 18.2, gm: 0.41 }),
    ];
    const rows = groupPeersForAxes(claims, PE, GM);
    expect(rows.map((r) => r.symbol)).toEqual(["INTC"]);
  });
});

// ── extractMedianForAxes ──────────────────────────────────────────────

describe("extractMedianForAxes", () => {
  it("pulls the median pair for any two metrics", () => {
    const claims = [
      claim(`Peer median: ${PE}`, 22.0),
      claim(`Peer median: ${GM}`, 0.48),
      claim(`Peer median: ${PS}`, 6.5),
      claim(`Peer median: ${EV}`, 18.4),
    ];
    expect(extractMedianForAxes(claims, PE, GM)).toEqual({
      x: 22.0,
      y: 0.48,
    });
    expect(extractMedianForAxes(claims, PS, GM)).toEqual({
      x: 6.5,
      y: 0.48,
    });
    expect(extractMedianForAxes(claims, EV, GM)).toEqual({
      x: 18.4,
      y: 0.48,
    });
  });

  it("returns null when either median is missing", () => {
    expect(
      extractMedianForAxes(
        [claim(`Peer median: ${PE}`, 22.0)],
        PE,
        GM,
      ),
    ).toBeNull();
  });

  it("returns null when either median is non-numeric", () => {
    expect(
      extractMedianForAxes(
        [
          claim(`Peer median: ${PE}`, null),
          claim(`Peer median: ${GM}`, 0.48),
        ],
        PE,
        GM,
      ),
    ).toBeNull();
  });
});

// ── Legacy groupPeers still works ────────────────────────────────────

describe("groupPeers (legacy compat)", () => {
  it("delegates to groupPeersForAxes(P/E, Gross margin) under the hood", () => {
    const claims = [
      ...peerClaims("AMD", { pe: 25.4, gm: 0.46 }),
      ...peerClaims("INTC", { pe: 18.2, gm: 0.41 }),
    ];
    const rows = groupPeers(claims);
    expect(rows.map((r) => r.symbol).sort()).toEqual(["AMD", "INTC"]);
    // Field names stay {pe, margin} on the legacy shape.
    expect(rows.find((r) => r.symbol === "AMD")).toEqual({
      symbol: "AMD",
      pe: 25.4,
      margin: 0.46,
    });
  });
});
