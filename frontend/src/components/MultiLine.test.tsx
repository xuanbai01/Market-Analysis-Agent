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
import { fireEvent, render } from "@testing-library/react";

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

  it("renders responsive width (100%) with viewBox carrying the dim props", () => {
    // Phase 4.3.B.1 — chart now scales to its parent container instead
    // of overflowing at hardcoded 560 px. The SVG width attribute is
    // always "100%"; the width prop survives in the viewBox so internal
    // x-positions (text labels, grid lines) stay at the right offsets.
    const { container } = render(
      <MultiLine series={[SERIES_A]} width={600} height={220} />,
    );
    const svg = container.querySelector("[data-testid='multi-line']");
    expect(svg?.getAttribute("width")).toBe("100%");
    expect(svg?.getAttribute("viewBox")).toBe("0 0 600 220");
    // Height attribute may stay numeric or also go responsive — the
    // height prop stays in viewBox either way.
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

  // Phase 4.3.X / cosmetic backlog from PR #50: design uses smooth
  // 2026-11 dogfood (tasks/dogfood-2026-11.md #8): smoothing invented
  // the shape between quarters ("a hill" where FCF actually fell in one
  // step). Quarterly data is drawn as straight segments between the
  // real points.
  it("draws straight segments between the real points, not curves", () => {
    const { container } = render(
      <MultiLine series={[SERIES_A, SERIES_B]} />,
    );
    const paths = container.querySelectorAll(
      "[data-testid='multi-line'] path[data-series-line]",
    );
    expect(paths.length).toBe(2);
    for (const path of paths) {
      const d = path.getAttribute("d") ?? "";
      expect(d).not.toMatch(/[CS]/);
      expect(d.match(/L/g)?.length).toBe(3);
    }
  });
});

// ── Readable charts (2026-11 dogfood #8) ─────────────────────────────
//
// "No baseline, no process shown — I can't read it." Every chart needs a
// labelled value axis with a visible baseline, every period labelled,
// the real data points marked, the latest values labelled at the line
// ends, and a hover readout.

const pct = (v: number) => `${(v * 100).toFixed(0)}%`;

function periods(n: number): string[] {
  return Array.from({ length: n }, (_, i) => {
    const year = 2021 + Math.floor(i / 4);
    return `${year}-Q${(i % 4) + 1}`;
  });
}

function longSeries(n: number, label: string): MultiLineSeries {
  return {
    label,
    color: "#6cb6ff",
    history: periods(n).map((period, i) => ({ period, value: 1 + i * 0.1 })),
  };
}

describe("MultiLine — axes, baseline, markers, labels, hover", () => {
  it("labels the value axis with clean ticks in the caller's format", () => {
    const { getAllByTestId } = render(
      <MultiLine series={[SERIES_A, SERIES_B]} formatValue={pct} includeZero />,
    );
    const ticks = getAllByTestId("multi-line-y-tick").map((t) => t.textContent);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    expect(ticks).toContain("0%");
    expect(ticks.every((t) => /^\d+%$/.test(t ?? ""))).toBe(true);
  });

  it("draws a solid baseline at zero when the scale includes it", () => {
    const { getByTestId } = render(
      <MultiLine series={[SERIES_A]} formatValue={pct} includeZero />,
    );
    const baseline = getByTestId("multi-line-baseline");
    expect(baseline.getAttribute("stroke-dasharray")).toBeNull();
  });

  it("draws the baseline between negative and positive values", () => {
    const losses: MultiLineSeries = {
      label: "Operating margin",
      color: "#e8c277",
      history: [
        { period: "2024-Q1", value: -0.41 },
        { period: "2024-Q2", value: -0.22 },
        { period: "2024-Q3", value: 0.05 },
      ],
    };
    const { getByTestId, getAllByTestId } = render(
      <MultiLine series={[losses]} formatValue={pct} />,
    );
    expect(getByTestId("multi-line-baseline")).not.toBeNull();
    const ticks = getAllByTestId("multi-line-y-tick").map((t) => t.textContent);
    expect(ticks.some((t) => t?.startsWith("-"))).toBe(true);
  });

  it("uses no dashed grid lines", () => {
    const { container } = render(<MultiLine series={[SERIES_A, SERIES_B]} />);
    expect(container.querySelectorAll("line[stroke-dasharray]").length).toBe(0);
  });

  it("labels every period when there are 8 or fewer", () => {
    const { getAllByTestId } = render(<MultiLine series={[SERIES_A, SERIES_B]} />);
    expect(getAllByTestId("multi-line-x-tick")).toHaveLength(4);
  });

  it("thins period labels on long histories but keeps both ends", () => {
    const series = longSeries(20, "EPS");
    const { getAllByTestId } = render(<MultiLine series={[series]} />);
    const ticks = getAllByTestId("multi-line-x-tick");
    expect(ticks.length).toBeLessThanOrEqual(6);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
    const titles = ticks.map((t) => t.getAttribute("data-period"));
    expect(titles[0]).toBe("2021-Q1");
    expect(titles[titles.length - 1]).toBe("2025-Q4");
  });

  it("marks every data point on short histories", () => {
    const { getAllByTestId } = render(<MultiLine series={[SERIES_A, SERIES_B]} />);
    expect(getAllByTestId("multi-line-marker")).toHaveLength(8);
  });

  it("marks only the latest point on long histories", () => {
    const { getAllByTestId } = render(<MultiLine series={[longSeries(20, "EPS")]} />);
    expect(getAllByTestId("multi-line-marker")).toHaveLength(1);
  });

  it("labels each line's latest value at its end", () => {
    const { getAllByTestId } = render(
      <MultiLine series={[SERIES_A, SERIES_B]} formatValue={pct} />,
    );
    const labels = getAllByTestId("multi-line-end-label").map((l) => l.textContent);
    expect(labels).toEqual(
      expect.arrayContaining(["Gross margin 76%", "Operating margin 48%"]),
    );
  });

  it("prefers a series' short label at the line end", () => {
    const { getAllByTestId } = render(
      <MultiLine series={[{ ...SERIES_A, shortLabel: "GM" }]} formatValue={pct} />,
    );
    expect(getAllByTestId("multi-line-end-label")[0].textContent).toBe("GM 76%");
  });

  it("keeps end labels from overlapping when lines end together", () => {
    const twin: MultiLineSeries = { ...SERIES_C, label: "Twin", history: SERIES_A.history };
    const { getAllByTestId } = render(<MultiLine series={[SERIES_A, twin]} />);
    const ys = getAllByTestId("multi-line-end-label").map((l) =>
      Number(l.getAttribute("y")),
    );
    expect(Math.abs(ys[0] - ys[1])).toBeGreaterThanOrEqual(11);
  });

  it("omits end labels when asked", () => {
    const { queryAllByTestId } = render(
      <MultiLine series={[SERIES_A]} showEndLabels={false} />,
    );
    expect(queryAllByTestId("multi-line-end-label")).toHaveLength(0);
  });

  it("shares one scale across charts given the same domain", () => {
    const a = render(<MultiLine series={[SERIES_A]} yDomain={[0, 1]} formatValue={pct} />);
    const aTicks = a.getAllByTestId("multi-line-y-tick").map((t) => t.textContent);
    a.unmount();
    const b = render(<MultiLine series={[SERIES_B]} yDomain={[0, 1]} formatValue={pct} />);
    const bTicks = b.getAllByTestId("multi-line-y-tick").map((t) => t.textContent);
    expect(bTicks).toEqual(aTicks);
  });

  it("shows every series' value for the hovered period, then hides", () => {
    const { container, getByTestId, queryByTestId } = render(
      <MultiLine series={[SERIES_A, SERIES_B]} formatValue={pct} />,
    );
    const svg = container.querySelector("[data-testid='multi-line']")!;
    // happy-dom has no layout; the chart falls back to the latest period.
    fireEvent.mouseMove(svg, { clientX: 10, clientY: 10 });
    const tip = getByTestId("multi-line-tooltip");
    expect(tip.textContent).toContain("2024-Q4");
    expect(tip.textContent).toContain("76%");
    expect(tip.textContent).toContain("48%");
    expect(getByTestId("multi-line-hover-guide")).not.toBeNull();
    fireEvent.mouseLeave(svg);
    expect(queryByTestId("multi-line-tooltip")).toBeNull();
  });

  it("adds the change from the previous period when asked", () => {
    const { container, getByTestId } = render(
      <MultiLine
        series={[SERIES_A]}
        formatValue={pct}
        formatChange={(now, prev) => `${((now / prev - 1) * 100).toFixed(0)}% QoQ`}
      />,
    );
    const svg = container.querySelector("[data-testid='multi-line']")!;
    // happy-dom has no layout; the chart falls back to the last period.
    fireEvent.mouseMove(svg, { clientX: 10, clientY: 10 });
    expect(getByTestId("multi-line-tooltip").textContent).toMatch(/QoQ/);
  });
});
