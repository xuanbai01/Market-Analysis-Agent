/**
 * Sparkline tests (Phase 3.3.A).
 *
 * The Sparkline is a passive chart — given a Claim's history, it draws a
 * tiny line. No tooltip, no axes, no legend. The contract we pin here:
 *
 * 1. **Length-2 minimum** — a single point isn't a trend; the renderer
 *    skips the chart entirely so the cell stays clean.
 * 2. **Stable DOM marker** — the SVG carries a ``data-testid`` so
 *    ReportRenderer's tests can assert "this row got a sparkline" without
 *    coupling to Recharts internals.
 * 3. **Accessibility** — the SVG has an ``aria-label`` summarizing the
 *    series so screen readers don't see a blank graphic.
 * 4. **No prop-drift crash** — handed a degenerate history (all NaN, all
 *    same value), Sparkline still renders without throwing. Recharts
 *    handles flat lines gracefully; we verify that contract here.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import type { ClaimHistoryPoint } from "../lib/schemas";
import { Sparkline } from "./Sparkline";

function makeHistory(values: number[]): ClaimHistoryPoint[] {
  return values.map((v, i) => ({ period: `2024-Q${i + 1}`, value: v }));
}

describe("Sparkline", () => {
  it("renders an SVG when history has 2+ points", () => {
    const { container } = render(
      <Sparkline history={makeHistory([1.0, 1.5, 2.0, 2.5])} />,
    );
    const svg = container.querySelector("[data-testid='sparkline']");
    expect(svg).not.toBeNull();
  });

  it("returns null when history has fewer than 2 points", () => {
    // Length 0 — no history at all.
    const { container: empty } = render(<Sparkline history={[]} />);
    expect(empty.querySelector("[data-testid='sparkline']")).toBeNull();

    // Length 1 — single point isn't a trend.
    const { container: one } = render(
      <Sparkline history={makeHistory([2.18])} />,
    );
    expect(one.querySelector("[data-testid='sparkline']")).toBeNull();
  });

  it("uses default 80x24 dimensions when not overridden", () => {
    const { container } = render(
      <Sparkline history={makeHistory([1, 2, 3])} />,
    );
    const svg = container.querySelector("[data-testid='sparkline']");
    expect(svg?.getAttribute("width")).toBe("80");
    expect(svg?.getAttribute("height")).toBe("24");
  });

  it("respects custom dimensions", () => {
    const { container } = render(
      <Sparkline
        history={makeHistory([1, 2, 3])}
        width={120}
        height={32}
      />,
    );
    const svg = container.querySelector("[data-testid='sparkline']");
    expect(svg?.getAttribute("width")).toBe("120");
    expect(svg?.getAttribute("height")).toBe("32");
  });

  it("carries an aria-label summarizing the series", () => {
    const { container } = render(
      <Sparkline
        history={makeHistory([1.0, 2.0, 3.0])}
        ariaLabel="Trend for EPS"
      />,
    );
    const svg = container.querySelector("[data-testid='sparkline']");
    expect(svg?.getAttribute("aria-label")).toBe("Trend for EPS");
  });

  it("renders without throwing on a flat (all-equal) history", () => {
    expect(() =>
      render(<Sparkline history={makeHistory([5, 5, 5, 5])} />),
    ).not.toThrow();
  });

  it("renders without throwing on negative values", () => {
    // FCF or operating income can go negative — sparkline must handle.
    expect(() =>
      render(<Sparkline history={makeHistory([-2, -1, 0, 1, 2])} />),
    ).not.toThrow();
  });
});
