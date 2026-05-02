/**
 * PeerScatter tests (Phase 3.3.C).
 *
 * Pin the external contract; let Recharts internals stay opaque:
 *
 * 1. Renders an SVG with ``data-testid='peer-scatter'`` when peers
 *    is non-empty.
 * 2. Returns null when peers is empty (subject + median alone don't
 *    justify the chart — peer comparison needs peers).
 * 3. Subject dot is visually distinct from peer dots (different
 *    fill / size attribute).
 * 4. Median dot is rendered when median prop is provided, skipped
 *    when undefined.
 * 5. Doesn't crash on subject undefined (EARNINGS focus mode).
 * 6. Custom width/height props honored.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import PeerScatter from "./PeerScatter";

const PEERS = [
  { symbol: "AMD", pe: 25.4, margin: 0.46 },
  { symbol: "INTC", pe: 18.2, margin: 0.41 },
  { symbol: "QCOM", pe: 14.8, margin: 0.55 },
];
const SUBJECT = { symbol: "NVDA", pe: 65.0, margin: 0.74 };
const MEDIAN = { pe: 18.2, margin: 0.46 };

describe("PeerScatter", () => {
  it("renders an SVG when peers is non-empty", () => {
    const { container } = render(<PeerScatter peers={PEERS} />);
    expect(
      container.querySelector("[data-testid='peer-scatter']"),
    ).not.toBeNull();
  });

  it("returns null when peers is empty", () => {
    const { container } = render(<PeerScatter peers={[]} />);
    expect(
      container.querySelector("[data-testid='peer-scatter']"),
    ).toBeNull();
  });

  it("renders without throwing when subject is undefined (EARNINGS focus mode)", () => {
    expect(() =>
      render(<PeerScatter peers={PEERS} median={MEDIAN} />),
    ).not.toThrow();
  });

  it("renders subject dot distinctly from peer dots", () => {
    // The subject is rendered as its own Recharts <Scatter> series
    // separate from the peers series. We assert both series are
    // present in the DOM via Recharts' .recharts-scatter class
    // marker.
    const { container } = render(
      <PeerScatter peers={PEERS} subject={SUBJECT} median={MEDIAN} />,
    );
    const scatters = container.querySelectorAll(".recharts-scatter");
    // peers + subject + median = 3 scatter series.
    expect(scatters.length).toBe(3);
  });

  it("renders only the peers scatter when subject and median are absent", () => {
    const { container } = render(<PeerScatter peers={PEERS} />);
    const scatters = container.querySelectorAll(".recharts-scatter");
    expect(scatters.length).toBe(1);
  });

  it("respects custom width and height", () => {
    const { container } = render(
      <PeerScatter peers={PEERS} width={500} height={320} />,
    );
    const svg = container.querySelector("[data-testid='peer-scatter']");
    expect(svg?.getAttribute("width")).toBe("500");
    expect(svg?.getAttribute("height")).toBe("320");
  });

  it("renders without throwing when only one peer has both metrics", () => {
    expect(() =>
      render(<PeerScatter peers={[PEERS[0]]} subject={SUBJECT} />),
    ).not.toThrow();
  });
});
