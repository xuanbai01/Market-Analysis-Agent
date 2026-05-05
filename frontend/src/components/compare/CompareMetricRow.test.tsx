/**
 * CompareMetricRow tests (Phase 4.6.A).
 *
 * Generic horizontal-bar row for both Valuation (lower=cheaper) and
 * Quality (higher=better) blocks. Each cell displays:
 *   - left side: A's value
 *   - middle: metric label + direction hint
 *   - right side: B's value
 *   - colored proportional bar between them
 *
 * Behaviors pinned:
 *   1. Renders one row per metric cell (data-row="compare-metric").
 *   2. Em-dashes when a value is null on either side.
 *   3. lowerIsBetter=true shows "lower = cheaper" hint.
 *   4. lowerIsBetter=false shows "higher = better" hint.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { CompareMetricRow } from "./CompareMetricRow";
import type { CompareMetricCell } from "../../lib/compare-extract";

const VALUATION_CELLS: CompareMetricCell[] = [
  {
    key: "forward_pe",
    label: "P/E FWD",
    description: "P/E ratio (forward, analyst consensus)",
    valueA: 32.1,
    valueB: 26.8,
    lowerIsBetter: true,
  },
  {
    key: "p_s",
    label: "P/S",
    description: "Price-to-sales ratio (trailing 12 months)",
    valueA: 24.4,
    valueB: 14.2,
    lowerIsBetter: true,
  },
  {
    key: "ev_ebitda",
    label: "EV/EBITDA",
    description: "Enterprise value to EBITDA",
    valueA: 41.2,
    valueB: 24.8,
    lowerIsBetter: true,
  },
];

const QUALITY_CELLS: CompareMetricCell[] = [
  {
    key: "gross_margin",
    label: "GROSS MARGIN",
    description: "Gross margin",
    valueA: 0.748,
    valueB: 0.738,
    lowerIsBetter: false,
  },
  {
    key: "operating_margin",
    label: "OPERATING MARGIN",
    description: "Operating margin",
    valueA: 0.612,
    valueB: 0.421,
    lowerIsBetter: false,
  },
];

describe("CompareMetricRow", () => {
  it("renders one row per cell with stable data-row marker", () => {
    const { container } = render(
      <CompareMetricRow title="Valuation" cells={VALUATION_CELLS} />,
    );
    expect(container.querySelectorAll("[data-row='compare-metric']")).toHaveLength(3);
  });

  it("renders an em-dash when a side's value is null", () => {
    const cells: CompareMetricCell[] = [
      { ...VALUATION_CELLS[0], valueA: null },
    ];
    const { container } = render(
      <CompareMetricRow title="Valuation" cells={cells} />,
    );
    expect(container.textContent ?? "").toContain("—");
  });

  it("shows 'lower = cheaper' hint when lowerIsBetter=true", () => {
    render(<CompareMetricRow title="Valuation" cells={VALUATION_CELLS} />);
    expect(screen.getByText(/lower = cheaper/i)).toBeInTheDocument();
  });

  it("shows 'higher = better' hint when lowerIsBetter=false", () => {
    render(<CompareMetricRow title="Quality" cells={QUALITY_CELLS} />);
    expect(screen.getByText(/higher = better/i)).toBeInTheDocument();
  });
});
