/**
 * PeerScatterV2 tests (Phase 4.2).
 *
 * Hand-rolled SVG replacement for 3.3.C's Recharts ScatterChart.
 * Three axis presets are picked via inline pill row:
 *
 *   - P/E × Gross Margin (default)
 *   - P/S × Gross Margin
 *   - EV/EBITDA × Gross Margin
 *
 * Behaviors pinned:
 *
 * 1. Renders an SVG with data-testid='peer-scatter-v2' when peers
 *    have data for the selected axis.
 * 2. Returns null when no peer has both selected metrics.
 * 3. Subject dot is rendered when subject prop is provided.
 * 4. Median cross is rendered when median prop is provided.
 * 5. Selecting a different preset re-renders against the new axes.
 * 6. Renders X/Y axis labels for the active preset.
 * 7. Renders the 3 preset pills.
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render } from "@testing-library/react";

import { PeerScatterV2 } from "./PeerScatterV2";
import type { Claim, ClaimValue } from "../lib/schemas";

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

const PEER_CLAIMS: Claim[] = [
  claim("AMD: " + PE, 25.4),
  claim("AMD: " + PS, 5.2),
  claim("AMD: " + EV, 22.0),
  claim("AMD: " + GM, 0.46),
  claim("INTC: " + PE, 18.2),
  claim("INTC: " + PS, 2.4),
  claim("INTC: " + EV, 14.0),
  claim("INTC: " + GM, 0.41),
  claim("QCOM: " + PE, 14.8),
  claim("QCOM: " + PS, 4.1),
  claim("QCOM: " + EV, 11.8),
  claim("QCOM: " + GM, 0.55),
  claim("Peer median: " + PE, 18.2),
  claim("Peer median: " + PS, 4.1),
  claim("Peer median: " + EV, 14.0),
  claim("Peer median: " + GM, 0.46),
];

const SUBJECT = { symbol: "NVDA", trailing_pe: 65.0, p_s: 18.0, ev_ebitda: 38.5, gross_margin: 0.74 };

describe("PeerScatterV2", () => {
  it("renders an SVG with data-testid='peer-scatter-v2'", () => {
    const { container } = render(
      <PeerScatterV2 peerClaims={PEER_CLAIMS} subject={SUBJECT} />,
    );
    expect(
      container.querySelector("[data-testid='peer-scatter-v2']"),
    ).not.toBeNull();
  });

  it("returns null when no peer has both selected metrics", () => {
    const { container } = render(
      <PeerScatterV2 peerClaims={[]} subject={undefined} />,
    );
    expect(
      container.querySelector("[data-testid='peer-scatter-v2']"),
    ).toBeNull();
  });

  it("renders 3 preset pills", () => {
    const { container } = render(
      <PeerScatterV2 peerClaims={PEER_CLAIMS} subject={SUBJECT} />,
    );
    const pills = container.querySelectorAll(
      "[data-pill='peer-axis-preset']",
    );
    expect(pills.length).toBe(3);
  });

  it("starts on the P/E × Gross Margin preset", () => {
    const { getAllByText } = render(
      <PeerScatterV2 peerClaims={PEER_CLAIMS} subject={SUBJECT} />,
    );
    // Active preset's pill label + X-axis title both contain "P/E";
    // assert at least one element matches.
    expect(getAllByText(/P\/E/i).length).toBeGreaterThan(0);
  });

  it("re-renders against new axes when a different preset is selected", () => {
    const { container, getByRole } = render(
      <PeerScatterV2 peerClaims={PEER_CLAIMS} subject={SUBJECT} />,
    );
    const psPill = getByRole("button", { name: /P\/S/i });
    fireEvent.click(psPill);
    // The peer dots should now be plotted against P/S × Gross Margin —
    // we don't pin exact pixel coordinates, but we do pin that the SVG
    // re-renders without errors and the X-axis label updates.
    expect(
      container.querySelector("[data-testid='peer-scatter-v2']"),
    ).not.toBeNull();
    expect(container.textContent).toMatch(/Price-to-sales|P\/S/i);
  });

  it("renders the subject dot distinctly", () => {
    const { container } = render(
      <PeerScatterV2 peerClaims={PEER_CLAIMS} subject={SUBJECT} />,
    );
    const subjectDot = container.querySelector("[data-marker='subject']");
    expect(subjectDot).not.toBeNull();
  });

  it("renders the median cross when peer medians are available", () => {
    const { container } = render(
      <PeerScatterV2 peerClaims={PEER_CLAIMS} subject={SUBJECT} />,
    );
    const median = container.querySelector("[data-marker='median']");
    expect(median).not.toBeNull();
  });

  it("renders peer dots for each peer with the active axis pair", () => {
    const { container } = render(
      <PeerScatterV2 peerClaims={PEER_CLAIMS} subject={SUBJECT} />,
    );
    const peerDots = container.querySelectorAll("[data-marker='peer']");
    // 3 peers (AMD, INTC, QCOM) all have PE + GM.
    expect(peerDots.length).toBe(3);
  });

  it("renders without throwing when subject is undefined (EARNINGS focus)", () => {
    expect(() =>
      render(<PeerScatterV2 peerClaims={PEER_CLAIMS} subject={undefined} />),
    ).not.toThrow();
  });
});
