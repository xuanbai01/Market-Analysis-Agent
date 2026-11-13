import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import type { OwnHistoryPanel } from "../lib/valuation-history-extract";
import { ValuationHistory } from "./ValuationHistory";

const years = (values: number[]) => values.map((v, i) => ({ period: String(2021 + i), value: v }));

const PE: OwnHistoryPanel = {
  key: "pe",
  label: "P/E",
  history: years([10, 12, 14, 16, 18]),
  median: 14,
  today: 28,
  premium: 1.0,
};
const PS: OwnHistoryPanel = {
  key: "ps",
  label: "Price / sales",
  history: years([4, 5, 6, 7, 8]),
  median: 6,
  today: 5.4,
  premium: -0.1,
};

describe("ValuationHistory", () => {
  it("renders nothing without panels", () => {
    const { container } = render(<ValuationHistory panels={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("draws one chart per multiple", () => {
    const { container } = render(<ValuationHistory panels={[PE, PS]} />);
    expect(screen.getAllByTestId("own-history-panel")).toHaveLength(2);
    expect(container.querySelectorAll("[data-testid='multi-line']")).toHaveLength(2);
  });

  it("states today, the median and the gap between them in words", () => {
    render(<ValuationHistory panels={[PE, PS]} />);
    const [pe, ps] = screen.getAllByTestId("own-history-panel");
    expect(within(pe).getByTestId("own-history-read")).toHaveTextContent(
      "Today 28.0× · median 14.0× · 100% above",
    );
    expect(within(ps).getByTestId("own-history-read")).toHaveTextContent(
      "Today 5.4× · median 6.0× · 10% below",
    );
  });

  it("ends the line at today and draws the median as a reference line", () => {
    const { container } = render(<ValuationHistory panels={[PE]} />);
    const ticks = [...container.querySelectorAll("[data-testid='multi-line-x-tick']")].map((t) => t.textContent);
    expect(ticks[0]).toBe("2021");
    expect(ticks[ticks.length - 1]).toBe("Today");
    expect(container.querySelector("[data-testid='multi-line-baseline']")).not.toBeNull();
    expect(container.querySelector("[data-testid='multi-line-end-label']")?.textContent).toBe("Today 28.0×");
  });

  it("without a reading for today, the line stops at the last year-end", () => {
    const { container } = render(<ValuationHistory panels={[{ ...PE, today: null, premium: null }]} />);
    const ticks = [...container.querySelectorAll("[data-testid='multi-line-x-tick']")].map((t) => t.textContent);
    expect(ticks[ticks.length - 1]).toBe("2025");
    expect(screen.getByTestId("own-history-read")).toHaveTextContent("No trailing figure today · median 14.0×");
  });

  it("without a median, it says how many year-ends there are instead", () => {
    render(<ValuationHistory panels={[{ ...PS, history: years([10, 5, 3, 4]), median: null, premium: null }]} />);
    expect(screen.getByTestId("own-history-read")).toHaveTextContent("Today 5.4× · 4 year-ends, too few for a median");
  });

  it("names an outlier year instead of letting it flatten the chart", () => {
    // Coca-Cola: a 2017 P/E of 158 on earnings cut by a one-off tax charge.
    const { container } = render(
      <ValuationHistory
        panels={[{ ...PE, history: years([25, 28, 158, 30, 27]), median: 28, today: 29, premium: 0.04 }]}
      />,
    );
    expect(screen.getByTestId("own-history-off-scale")).toHaveTextContent("off the scale: 2023 at 158.0×");
    const ticks = [...container.querySelectorAll("[data-testid='multi-line-y-tick']")].map((t) =>
      Number(t.textContent),
    );
    expect(Math.max(...ticks)).toBeLessThan(60);
    // The line does not run to the outlier: a marker at the top edge stands in.
    expect(container.querySelectorAll("[data-testid='multi-line-off-scale']")).toHaveLength(1);
  });

  it("keeps a high year on the scale when the other years reach nearly as high", () => {
    // XOM price / free cash flow: 84.9 in 2015 is over four times the
    // median, but 2016 is at 63.7, so the axis runs that high anyway.
    const { container } = render(
      <ValuationHistory
        panels={[{ ...PE, history: years([84.9, 63.7, 24.3, 17.7, 12.1]), median: 19.8, today: 16, premium: -0.19 }]}
      />,
    );
    expect(screen.queryByTestId("own-history-off-scale")).toBeNull();
    expect(container.querySelectorAll("[data-testid='multi-line-off-scale']")).toHaveLength(0);
  });

  it("labels axis ticks without rounding them into uneven steps", () => {
    // Price / sales near 1: ticks at 0.75, 1, 1.25 … must not read 0.8, 1, 1.3.
    const { container } = render(
      <ValuationHistory
        panels={[{ ...PS, history: years([1.4, 1.9, 1.0, 0.9, 1.6]), median: 1.2, today: 1.8, premium: 0.5 }]}
      />,
    );
    const ticks = [...container.querySelectorAll("[data-testid='multi-line-y-tick']")].map((t) =>
      Number(t.textContent),
    );
    const steps = ticks.slice(1).map((t, i) => Number((t - ticks[i]).toFixed(4)));
    expect(new Set(steps).size).toBe(1);
  });

  it("keeps every year on the scale when none is far from the median", () => {
    render(<ValuationHistory panels={[PE]} />);
    expect(screen.queryByTestId("own-history-off-scale")).toBeNull();
  });

  it("leaves a gap for a year with no multiple instead of joining its neighbours", () => {
    // XOM: a loss in 2020, so no P/E for that year.
    const gappy = [
      { period: "2021", value: 20 },
      { period: "2022", value: 22 },
      { period: "2024", value: 14 },
      { period: "2025", value: 18 },
    ];
    const { container } = render(
      <ValuationHistory panels={[{ ...PE, history: gappy, median: null, today: null, premium: null }]} />,
    );
    const d = container.querySelector("[data-series-line]")?.getAttribute("d") ?? "";
    expect(d.match(/M/g)).toHaveLength(2);
  });

  it("says what the points are", () => {
    render(<ValuationHistory panels={[PE]} />);
    expect(screen.getByTestId("own-history-note")).toHaveTextContent("fiscal year-end");
    expect(screen.getByTestId("own-history-note")).toHaveTextContent("trailing 12 months");
  });
});
