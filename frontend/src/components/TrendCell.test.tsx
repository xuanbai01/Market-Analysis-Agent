/**
 * TrendCell — the "Trend" column of the Quality / report claim tables.
 *
 * 2026-11 dogfood #10: the bare sparkline implied trends the data can't
 * support. ROIC and ROE carry only 2 points, so their "falling" line was
 * two dots joined, and min–max autoscaling made a 3-point move look like
 * a crash. The cell now states the change since the first period, marks
 * the line's ends, and draws no line under 3 points.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { TrendCell } from "./TrendCell";
import type { ClaimHistoryPoint } from "../lib/schemas";

const FCF_MARGIN: ClaimHistoryPoint[] = [
  { period: "2025-Q3", value: 0.2882 },
  { period: "2025-Q4", value: 0.3879 },
  { period: "2026-Q1", value: 0.5123 },
  { period: "2026-Q2", value: 0.5953 },
  { period: "2026-Q3", value: 0.2224 },
];

const ROIC: ClaimHistoryPoint[] = [
  { period: "2026-Q2", value: 0.6286 },
  { period: "2026-Q3", value: 0.595 },
];

describe("TrendCell", () => {
  it("draws a sparkline and states the change in points for fractions", () => {
    const { getByTestId, queryByTestId } = render(
      <TrendCell history={FCF_MARGIN} unit="fraction" label="FCF margin" />,
    );
    expect(queryByTestId("sparkline")).not.toBeNull();
    expect(getByTestId("trend-delta").textContent).toBe("▼ 6.6 pts");
    expect(getByTestId("trend-since").textContent).toBe("since 2025-Q3");
  });

  it("states percent-unit changes in points too", () => {
    const { getByTestId } = render(
      <TrendCell
        history={[
          { period: "2024-01", value: 4.1 },
          { period: "2024-02", value: 4.3 },
          { period: "2024-03", value: 4.6 },
        ]}
        unit="percent"
      />,
    );
    expect(getByTestId("trend-delta").textContent).toBe("▲ 0.5 pts");
  });

  it("states dollar and ratio changes as a percent change", () => {
    const { getByTestId } = render(
      <TrendCell
        history={[
          { period: "2025-Q3", value: 0.0772 },
          { period: "2025-Q4", value: 0.0668 },
          { period: "2026-Q3", value: 0.1102 },
        ]}
        unit="usd_per_share"
      />,
    );
    expect(getByTestId("trend-delta").textContent).toBe("▲ 43%");
  });

  it("falls back to the absolute change when the start is zero or negative", () => {
    const { getByTestId } = render(
      <TrendCell
        history={[
          { period: "2025-Q3", value: -0.55 },
          { period: "2025-Q4", value: 0.2 },
          { period: "2026-Q1", value: 0.9 },
        ]}
        unit="usd_per_share"
      />,
    );
    expect(getByTestId("trend-delta").textContent).toBe("▲ $1.45");
  });

  it("draws no line for two points and says how little data there is", () => {
    const { getByTestId, queryByTestId } = render(
      <TrendCell history={ROIC} unit="fraction" label="ROIC" />,
    );
    expect(queryByTestId("sparkline")).toBeNull();
    expect(getByTestId("trend-delta").textContent).toBe("▼ 3.4 pts");
    expect(getByTestId("trend-sparse").textContent).toBe("2 periods only");
  });

  it("calls an unchanged series flat", () => {
    const { getByTestId } = render(
      <TrendCell
        history={[
          { period: "2025-Q3", value: 0.5 },
          { period: "2025-Q4", value: 0.6 },
          { period: "2026-Q1", value: 0.5 },
        ]}
        unit="fraction"
      />,
    );
    expect(getByTestId("trend-delta").textContent).toBe("flat");
  });

  it("renders nothing for fewer than two points", () => {
    const { container } = render(
      <TrendCell history={[{ period: "2026-Q3", value: 1 }]} unit="ratio" />,
    );
    expect(container.textContent).toBe("");
  });
});
