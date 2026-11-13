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

  it("says what the points are", () => {
    render(<ValuationHistory panels={[PE]} />);
    expect(screen.getByTestId("own-history-note")).toHaveTextContent("fiscal year-end");
    expect(screen.getByTestId("own-history-note")).toHaveTextContent("trailing 12 months");
  });
});
