/**
 * LineChart tests (Phase 4.1).
 *
 * Bigger sibling of Sparkline — same hand-rolled SVG philosophy. Used
 * by the hero card for the 60-day price chart. Behaviors pinned:
 *
 * 1. Renders SVG with the documented data-testid when given data.
 * 2. Returns null on empty data (defense-in-depth — caller should
 *    branch first).
 * 3. Honors width/height props.
 * 4. Renders an area fill when ``areaFill`` is true.
 * 5. Doesn't throw on flat (constant) data.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { LineChart } from "./LineChart";

const SAMPLE = [
  { ts: "2026-04-01T00:00:00Z", close: 100, volume: 1_000_000 },
  { ts: "2026-04-02T00:00:00Z", close: 102, volume: 1_100_000 },
  { ts: "2026-04-03T00:00:00Z", close: 101, volume: 950_000 },
  { ts: "2026-04-04T00:00:00Z", close: 105, volume: 1_400_000 },
];

describe("LineChart", () => {
  it("renders an SVG with data-testid='line-chart'", () => {
    const { container } = render(<LineChart data={SAMPLE} />);
    expect(
      container.querySelector("[data-testid='line-chart']"),
    ).not.toBeNull();
  });

  it("returns null on empty data", () => {
    const { container } = render(<LineChart data={[]} />);
    expect(
      container.querySelector("[data-testid='line-chart']"),
    ).toBeNull();
  });

  it("renders responsive width (100%) with viewBox carrying the dim props", () => {
    // Phase 4.3.B.1 — chart no longer overflows the hero card on
    // narrow viewports. The SVG width is always "100%"; viewBox
    // carries the explicit dimensions so internal coordinates stay
    // correct.
    const { container } = render(
      <LineChart data={SAMPLE} width={600} height={200} />,
    );
    const svg = container.querySelector("[data-testid='line-chart']");
    expect(svg?.getAttribute("width")).toBe("100%");
    expect(svg?.getAttribute("viewBox")).toBe("0 0 600 200");
  });

  it("renders an area fill path when areaFill is true", () => {
    const { container } = render(
      <LineChart data={SAMPLE} areaFill={true} />,
    );
    // Area renders as a closed path — test by counting <path> elements
    // (line + area = 2 vs line only = 1).
    const paths = container.querySelectorAll(
      "[data-testid='line-chart'] path",
    );
    expect(paths.length).toBeGreaterThanOrEqual(2);
  });

  it("renders without throwing on flat data", () => {
    const flat = SAMPLE.map((d) => ({ ...d, close: 100 }));
    expect(() => render(<LineChart data={flat} />)).not.toThrow();
  });
});
