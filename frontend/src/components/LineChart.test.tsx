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
import { fireEvent, render } from "@testing-library/react";

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

  // Phase 4.3.B.2 — axis labels + hover tooltip. The pre-4.3.B.2
  // chart was decorative — you saw the shape but couldn't read prices
  // or dates. Two opt-in props:
  //   - showAxes: render y-axis min/max price labels + x-axis first/
  //     last date labels.
  //   - showTooltip: enable mousemove → guide-line + nearest-point dot
  //     + floating tooltip with exact date + price.
  // Both default to false so today's lean callers (none beyond
  // HeroCard) keep working.

  describe("axis labels (showAxes)", () => {
    it("does not render axis labels by default", () => {
      const { container } = render(<LineChart data={SAMPLE} />);
      expect(
        container.querySelector("[data-testid='line-chart-y-axis-max']"),
      ).toBeNull();
      expect(
        container.querySelector("[data-testid='line-chart-x-axis-start']"),
      ).toBeNull();
    });

    it("renders y-axis min/max price labels when showAxes is true", () => {
      const { container } = render(
        <LineChart data={SAMPLE} showAxes={true} />,
      );
      const yMax = container.querySelector(
        "[data-testid='line-chart-y-axis-max']",
      );
      const yMin = container.querySelector(
        "[data-testid='line-chart-y-axis-min']",
      );
      expect(yMax).not.toBeNull();
      expect(yMin).not.toBeNull();
      // Sample max = 105, min = 100; both rendered as "$X.XX".
      expect(yMax!.textContent).toMatch(/\$105\.00/);
      expect(yMin!.textContent).toMatch(/\$100\.00/);
    });

    it("renders x-axis first/last date labels when showAxes is true", () => {
      const { container } = render(
        <LineChart data={SAMPLE} showAxes={true} />,
      );
      const xStart = container.querySelector(
        "[data-testid='line-chart-x-axis-start']",
      );
      const xEnd = container.querySelector(
        "[data-testid='line-chart-x-axis-end']",
      );
      expect(xStart).not.toBeNull();
      expect(xEnd).not.toBeNull();
      // Format is locale-dependent; assert that the day numbers
      // (1 and 4) appear in the rendered labels.
      expect(xStart!.textContent).toMatch(/1/);
      expect(xEnd!.textContent).toMatch(/4/);
    });
  });

  describe("hover tooltip (showTooltip)", () => {
    it("does not render hover artifacts before any mouse interaction", () => {
      const { container } = render(
        <LineChart data={SAMPLE} showTooltip={true} />,
      );
      expect(
        container.querySelector("[data-testid='line-chart-hover-guide']"),
      ).toBeNull();
      expect(
        container.querySelector("[data-testid='line-chart-hover-dot']"),
      ).toBeNull();
      expect(
        container.querySelector("[data-testid='line-chart-hover-tooltip']"),
      ).toBeNull();
    });

    it("renders guide line + dot + tooltip on mousemove when showTooltip is true", () => {
      const { container } = render(
        <LineChart data={SAMPLE} showTooltip={true} />,
      );
      const svg = container.querySelector("[data-testid='line-chart']");
      expect(svg).not.toBeNull();
      fireEvent.mouseMove(svg!, { clientX: 50, clientY: 50 });
      expect(
        container.querySelector("[data-testid='line-chart-hover-guide']"),
      ).not.toBeNull();
      expect(
        container.querySelector("[data-testid='line-chart-hover-dot']"),
      ).not.toBeNull();
      expect(
        container.querySelector("[data-testid='line-chart-hover-tooltip']"),
      ).not.toBeNull();
    });

    it("tooltip text carries a price ($) and a date when active", () => {
      const { container } = render(
        <LineChart data={SAMPLE} showTooltip={true} />,
      );
      const svg = container.querySelector("[data-testid='line-chart']");
      fireEvent.mouseMove(svg!, { clientX: 100, clientY: 50 });
      const tooltip = container.querySelector(
        "[data-testid='line-chart-hover-tooltip']",
      );
      expect(tooltip).not.toBeNull();
      const text = tooltip!.textContent ?? "";
      // Some price ($XX.XX) and some part of a date (a digit).
      expect(text).toMatch(/\$\d/);
      expect(text).toMatch(/\d/);
    });

    it("clears hover artifacts on mouseleave", () => {
      const { container } = render(
        <LineChart data={SAMPLE} showTooltip={true} />,
      );
      const svg = container.querySelector("[data-testid='line-chart']");
      fireEvent.mouseMove(svg!, { clientX: 50, clientY: 50 });
      expect(
        container.querySelector("[data-testid='line-chart-hover-tooltip']"),
      ).not.toBeNull();
      fireEvent.mouseLeave(svg!);
      expect(
        container.querySelector("[data-testid='line-chart-hover-guide']"),
      ).toBeNull();
      expect(
        container.querySelector("[data-testid='line-chart-hover-dot']"),
      ).toBeNull();
      expect(
        container.querySelector("[data-testid='line-chart-hover-tooltip']"),
      ).toBeNull();
    });

    it("does not respond to mousemove when showTooltip is false", () => {
      const { container } = render(<LineChart data={SAMPLE} />);
      const svg = container.querySelector("[data-testid='line-chart']");
      fireEvent.mouseMove(svg!, { clientX: 50, clientY: 50 });
      expect(
        container.querySelector("[data-testid='line-chart-hover-tooltip']"),
      ).toBeNull();
    });
  });
});
