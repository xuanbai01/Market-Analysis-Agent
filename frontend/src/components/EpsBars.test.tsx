/**
 * EpsBars tests (Phase 4.1).
 *
 * 20-bar EPS chart for the EarningsCard. Each bar shows a quarter's
 * actual EPS; color encodes beat (>= estimate) vs miss (< estimate);
 * the estimate value renders as a small horizontal tick across the
 * top of each bar.
 *
 * Behaviors pinned:
 * 1. One bar per ``actual`` history point.
 * 2. Beat bars use the pos color; miss bars use the neg color.
 * 3. Estimate ticks render only when there's a matching estimate
 *    point for the same period.
 * 4. Returns null when actual is empty.
 * 5. Width/height honored.
 * 6. Negative actuals (loss-making companies) render without crash.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { EpsBars } from "./EpsBars";
import type { ClaimHistoryPoint } from "../lib/schemas";

function quarters(values: number[]): ClaimHistoryPoint[] {
  return values.map((v, i) => ({ period: `2024-Q${(i % 4) + 1}`, value: v }));
}

describe("EpsBars", () => {
  it("renders one bar per actual history point", () => {
    const actual = quarters([1, 2, 3, 4, 5]);
    const { container } = render(<EpsBars actual={actual} estimate={[]} />);
    const bars = container.querySelectorAll(
      "[data-testid='eps-bars'] [data-bar='actual']",
    );
    expect(bars.length).toBe(5);
  });

  it("returns null when actual is empty", () => {
    const { container } = render(<EpsBars actual={[]} estimate={[]} />);
    expect(container.querySelector("[data-testid='eps-bars']")).toBeNull();
  });

  it("colors beat bars and miss bars differently", () => {
    // Q1 actual=2 estimate=1 (beat). Q2 actual=1 estimate=2 (miss).
    const actual: ClaimHistoryPoint[] = [
      { period: "2024-Q1", value: 2 },
      { period: "2024-Q2", value: 1 },
    ];
    const estimate: ClaimHistoryPoint[] = [
      { period: "2024-Q1", value: 1 },
      { period: "2024-Q2", value: 2 },
    ];
    const { container } = render(
      <EpsBars actual={actual} estimate={estimate} />,
    );
    const bars = container.querySelectorAll(
      "[data-testid='eps-bars'] [data-bar='actual']",
    );
    // The two bars should carry different fill attributes.
    const fillQ1 = bars[0].getAttribute("fill");
    const fillQ2 = bars[1].getAttribute("fill");
    expect(fillQ1).not.toBe(fillQ2);
  });

  it("renders estimate ticks for periods that have estimates", () => {
    const actual = quarters([1, 2, 3]);
    const estimate = quarters([0.9, 1.9, 2.9]);
    const { container } = render(
      <EpsBars actual={actual} estimate={estimate} />,
    );
    const ticks = container.querySelectorAll(
      "[data-testid='eps-bars'] [data-tick='estimate']",
    );
    expect(ticks.length).toBe(3);
  });

  it("skips estimate ticks for actuals without matching estimates", () => {
    const actual = quarters([1, 2, 3]);
    const estimate: ClaimHistoryPoint[] = [
      { period: "2024-Q1", value: 0.9 },
      // Q2, Q3 have no estimate
    ];
    const { container } = render(
      <EpsBars actual={actual} estimate={estimate} />,
    );
    const ticks = container.querySelectorAll(
      "[data-testid='eps-bars'] [data-tick='estimate']",
    );
    expect(ticks.length).toBe(1);
  });

  it("renders without throwing on negative actuals (RIVN-class)", () => {
    const actual = quarters([-1, -2, -1.5, -3]);
    expect(() =>
      render(<EpsBars actual={actual} estimate={[]} />),
    ).not.toThrow();
  });

  it("respects custom width and height", () => {
    const { container } = render(
      <EpsBars
        actual={quarters([1, 2, 3])}
        estimate={[]}
        width={500}
        height={180}
      />,
    );
    const svg = container.querySelector("[data-testid='eps-bars']");
    // Phase 4.3.B.1 — responsive width to fit narrow earnings columns.
    expect(svg?.getAttribute("width")).toBe("100%");
    expect(svg?.getAttribute("viewBox")).toBe("0 0 500 180");
  });
});
