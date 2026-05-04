/**
 * ValuationCard tests (Phase 4.2).
 *
 * Replaces the Valuation + Peers sections in ReportRenderer with a
 * single dedicated card. Three-region layout:
 *
 *   header (kicker + ticker)
 *   4-cell matrix: trailing P/E, forward P/E, P/S, EV/EBITDA — each
 *     cell shows subject value + peer median + horizontal percentile
 *     bar (peer min → max with subject dot).
 *   PeerScatterV2 with selectable axes.
 *
 * Pinned behaviors:
 *
 * 1. Renders 4 valuation cells.
 * 2. Renders a PeerScatterV2 SVG when peer claims exist.
 * 3. Subject values appear in the matrix cells.
 * 4. Renders the section summary (Valuation summary preferred, else
 *    Peers summary).
 * 5. Doesn't crash when peer / valuation sections are absent.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { ValuationCard } from "./ValuationCard";
import {
  HEALTHY_LAYOUT_SIGNALS,
  type Claim,
  type ClaimValue,
  type ResearchReport,
  type Section,
} from "../lib/schemas";

function claim(description: string, value: ClaimValue): Claim {
  return {
    description,
    value,
    source: { tool: "yfinance", fetched_at: "2026-05-03T14:00:00+00:00" },
    history: [],
  };
}

function section(title: string, claims: Claim[], summary = ""): Section {
  return { title, claims, summary, confidence: "high" };
}

const PE = "P/E ratio (trailing 12 months)";
const FWD_PE = "P/E ratio (forward, analyst consensus)";
const PS = "Price-to-sales ratio (trailing 12 months)";
const EVE = "Enterprise value to EBITDA";
const GM = "Gross margin";

function buildReport(opts: {
  symbol?: string;
  valuationClaims?: Claim[];
  peersClaims?: Claim[];
  valuationSummary?: string;
  peersSummary?: string;
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
      section(
        "Valuation",
        opts.valuationClaims ?? [
          claim(PE, 28.5),
          claim(FWD_PE, 24.1),
          claim(PS, 18.0),
          claim(EVE, 22.4),
        ],
        opts.valuationSummary ?? "",
      ),
      section(
        "Peers",
        opts.peersClaims ?? [
          claim("AMD: " + PE, 25.4),
          claim("AMD: " + GM, 0.46),
          claim("INTC: " + PE, 18.2),
          claim("INTC: " + GM, 0.41),
          claim("Peer median: " + PE, 22.0),
          claim("Peer median: " + GM, 0.44),
        ],
        opts.peersSummary ?? "",
      ),
    ],
  };
}

describe("ValuationCard", () => {
  it("renders 4 valuation cells", () => {
    const { container } = render(<ValuationCard report={buildReport()} />);
    const cells = container.querySelectorAll("[data-cell='valuation-metric']");
    expect(cells.length).toBe(4);
  });

  it("renders subject values inside the matrix cells", () => {
    const { getByTestId } = render(<ValuationCard report={buildReport()} />);
    expect(getByTestId("cell-trailing_pe").textContent).toContain("28.5");
    expect(getByTestId("cell-forward_pe").textContent).toContain("24.1");
    expect(getByTestId("cell-p_s").textContent).toContain("18.0");
    expect(getByTestId("cell-ev_ebitda").textContent).toContain("22.4");
  });

  it("renders an em-dash when subject value is missing", () => {
    const report = buildReport({
      valuationClaims: [], // all subject values missing
    });
    const { getByTestId } = render(<ValuationCard report={report} />);
    expect(getByTestId("cell-trailing_pe").textContent).toContain("—");
  });

  it("renders the PeerScatterV2 SVG when peer claims exist", () => {
    const { container } = render(<ValuationCard report={buildReport()} />);
    expect(
      container.querySelector("[data-testid='peer-scatter-v2']"),
    ).not.toBeNull();
  });

  it("renders the Valuation summary prose when present", () => {
    const { getByText } = render(
      <ValuationCard
        report={buildReport({
          valuationSummary: "Trades at a premium to peers.",
        })}
      />,
    );
    expect(getByText("Trades at a premium to peers.")).not.toBeNull();
  });

  it("renders without throwing when peers section is empty", () => {
    expect(() =>
      render(
        <ValuationCard report={buildReport({ peersClaims: [] })} />,
      ),
    ).not.toThrow();
  });

  // Phase 4.3.X / cosmetic backlog from PR #50: ValuationCard should
  // surface "n = X peers · sector medians" so the user sees how many
  // peers the percentile bars reflect (a 6-peer comparison reads
  // differently than a 2-peer comparison).
  it("renders 'n = X peers' annotation reflecting peer count", () => {
    const peers = [
      claim("AMD: " + PE, 25.4),
      claim("INTC: " + PE, 18.2),
      claim("AVGO: " + PE, 35.7),
      claim("Peer median: " + PE, 22.0),
    ];
    const { container } = render(
      <ValuationCard report={buildReport({ peersClaims: peers })} />,
    );
    const annotation = container.querySelector(
      "[data-testid='valuation-peer-count']",
    );
    expect(annotation).not.toBeNull();
    // 3 peers: AMD, INTC, AVGO (the "Peer median" claim isn't a peer).
    expect(annotation!.textContent).toMatch(/n\s*=\s*3/i);
    expect(annotation!.textContent?.toLowerCase()).toContain("peer");
  });

  it("renders without throwing when valuation section is absent", () => {
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
    expect(() => render(<ValuationCard report={report} />)).not.toThrow();
  });
});
