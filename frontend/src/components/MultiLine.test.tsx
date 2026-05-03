/**
 * MultiLine tests (Phase 4.2).
 *
 * Hand-rolled SVG multi-series chart. Used by QualityCard for the
 * gross/operating/FCF margin trio. 2-4 series share a common period
 * axis with auto-detected y-range. Pinned behaviors:
 *
 * 1. Renders an SVG with data-testid='multi-line'.
 * 2. Returns null when given no series.
 * 3. Returns null when every series has < 2 points (nothing to draw).
 * 4. Renders one <path> per series that has >= 2 points.
 * 5. Honors width/height props.
 * 6. Renders the series legend when ``showLegend`` (default true).
 * 7. Drops series with < 2 points but still renders the rest.
 * 8. Stable on flat data (all values equal — y-range = 0).
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { MultiLine } from "./MultiLine";
import type { MultiLineSeries } from "./MultiLine";

const SERIES_A: MultiLineSeries = {
  label: "Gross margin",
  color: "#7ad0a6",
  history: [
    { period: "2024-Q1", value: 0.72 },
    { period: "2024-Q2", value: 0.74 },
    { period: "2024-Q3", value: 0.75 },
    { period: "2024-Q4", value: 0.76 },
  ],
};

const SERIES_B: MultiLineSeries = {
  label: "Operating margin",
  color: "#c2d97a",
  history: [
    { period: "2024-Q1", value: 0.32 },
    { period: "2024-Q2", value: 0.36 },
    { period: "2024-Q3", value: 0.42 },
    { period: "2024-Q4", value: 0.48 },
  ],
};

const SERIES_C: MultiLineSeries = {
  label: "FCF margin",
  color: "#e8c277",
  history: [
    { period: "2024-Q1", value: 0.35 },
    { period: "2024-Q2", value: 0.40 },
    { period: "2024-Q3", value: 0.45 },
    { period: "2024-Q4", value: 0.50 },
  ],
};

describe("MultiLine", () => {
  it("renders an SVG with data-testid='multi-line'", () => {
    const { container } = render(
      <MultiLine series={[SERIES_A, SERIES_B, SERIES_C]} />,
    );
    expect(
      container.querySelector("[data-testid='multi-line']"),
    ).not.toBeNull();
  });

  it("returns null when given an empty series list", () => {
    const { container } = render(<MultiLine series={[]} />);
    expect(
      container.querySelector("[data-testid='multi-line']"),
    ).toBeNull();
  });

  it("returns null when every series has < 2 points", () => {
    const tinyA: MultiLineSeries = {
      ...SERIES_A,
      history: SERIES_A.history.slice(0, 1),
    };
    const tinyB: MultiLineSeries = { ...SERIES_B, history: [] };
    const { container } = render(<MultiLine series={[tinyA, tinyB]} />);
    expect(
      container.querySelector("[data-testid='multi-line']"),
    ).toBeNull();
  });

  it("renders one <path> per series with >= 2 points", () => {
    const { container } = render(
      <MultiLine series={[SERIES_A, SERIES_B]} />,
    );
    const paths = container.querySelectorAll(
      "[data-testid='multi-line'] path[data-series-line]",
    );
    expect(paths.length).toBe(2);
  });

  it("honors width and height props", () => {
    const { container } = render(
      <MultiLine series={[SERIES_A]} width={600} height={220} />,
    );
    const svg = container.querySelector("[data-testid='multi-line']");
    expect(svg?.getAttribute("width")).toBe("600");
    expect(svg?.getAttribute("height")).toBe("220");
  });

  it("renders a legend chip per series by default", () => {
    const { getByText } = render(
      <MultiLine series={[SERIES_A, SERIES_B, SERIES_C]} />,
    );
    expect(getByText("Gross margin")).not.toBeNull();
    expect(getByText("Operating margin")).not.toBeNull();
    expect(getByText("FCF margin")).not.toBeNull();
  });

  it("drops series with < 2 points but renders the rest", () => {
    const tinyB: MultiLineSeries = {
      ...SERIES_B,
      history: SERIES_B.history.slice(0, 1),
    };
    const { container } = render(<MultiLine series={[SERIES_A, tinyB]} />);
    const paths = container.querySelectorAll(
      "[data-testid='multi-line'] path[data-series-line]",
    );
    expect(paths.length).toBe(1);
  });

  it("renders without throwing when every value in a series is identical", () => {
    const flat: MultiLineSeries = {
      ...SERIES_A,
      history: SERIES_A.history.map((p) => ({ ...p, value: 0.5 })),
    };
    expect(() => render(<MultiLine series={[flat]} />)).not.toThrow();
  });
});
