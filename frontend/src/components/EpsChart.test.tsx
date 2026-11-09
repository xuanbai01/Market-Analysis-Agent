import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { EpsChart } from "./EpsChart";
import type { ClaimHistoryPoint } from "../lib/schemas";

function quarters(n: number, start = 2022): string[] {
  return Array.from({ length: n }, (_, i) => `${start + Math.floor(i / 4)}-Q${(i % 4) + 1}`);
}

function series(periods: string[], values: number[]): ClaimHistoryPoint[] {
  return periods.map((period, i) => ({ period, value: values[i] }));
}

const P = quarters(8);
const ACTUAL = series(P, [0.5, 0.6, 0.55, 0.7, 0.65, 0.8, 0.75, 0.9]);
const ESTIMATE = series(P, [0.48, 0.58, 0.6, 0.66, 0.62, 0.78, 0.8, 0.85]);

describe("EpsChart", () => {
  it("draws a filled dot for each actual and a ring for each consensus", () => {
    const { container } = render(<EpsChart actual={ACTUAL} estimate={ESTIMATE} />);
    expect(container.querySelectorAll("[data-mark='actual']")).toHaveLength(8);
    expect(container.querySelectorAll("[data-mark='estimate']")).toHaveLength(8);
  });

  it("marks each quarter as a beat or a miss", () => {
    const { container } = render(<EpsChart actual={ACTUAL} estimate={ESTIMATE} />);
    const results = Array.from(container.querySelectorAll("[data-mark='actual']")).map((d) =>
      d.getAttribute("data-result"),
    );
    // Q3 '22 (0.55 vs 0.60) and Q3 '23 (0.75 vs 0.80) missed.
    expect(results).toEqual(["beat", "beat", "miss", "beat", "beat", "beat", "miss", "beat"]);
  });

  it("has a dollar value axis and labels each year's first quarter plus the latest", () => {
    const { container } = render(<EpsChart actual={ACTUAL} estimate={ESTIMATE} />);
    const yTicks = Array.from(container.querySelectorAll("[data-testid='eps-y-tick']")).map((t) => t.textContent);
    expect(yTicks.length).toBeGreaterThanOrEqual(3);
    expect(yTicks.every((t) => t?.startsWith("$"))).toBe(true);
    const xTicks = Array.from(container.querySelectorAll("[data-testid='eps-x-tick']")).map((t) => t.textContent);
    expect(xTicks).toEqual(["Q1 '22", "Q1 '23", "Q4 '23"]);
  });

  it("draws a zero line when EPS crosses zero", () => {
    const losses = series(P.slice(0, 4), [-0.6, -0.3, 0.05, 0.2]);
    const { container } = render(<EpsChart actual={losses} estimate={[]} />);
    expect(container.querySelector("[data-testid='eps-zero-line']")).not.toBeNull();
    // No consensus → no rings, and every actual is drawn as neutral.
    expect(container.querySelectorAll("[data-mark='estimate']")).toHaveLength(0);
    expect(container.querySelector("[data-result='beat']")).toBeNull();
  });

  it("explains a quarter on hover", () => {
    const { container } = render(<EpsChart actual={ACTUAL} estimate={ESTIMATE} />);
    const target = container.querySelectorAll("[data-testid='eps-hit']")[2];
    fireEvent.mouseEnter(target);
    const tip = screen.getByTestId("eps-tooltip");
    expect(tip.textContent).toContain("Q3 '22");
    expect(tip.textContent).toContain("$0.55");
    expect(tip.textContent).toContain("$0.60");
    expect(tip.textContent).toContain("-8.3%");
    fireEvent.mouseLeave(target);
    expect(screen.queryByTestId("eps-tooltip")).toBeNull();
  });

  it("names both marks in a legend", () => {
    render(<EpsChart actual={ACTUAL} estimate={ESTIMATE} />);
    expect(screen.getByText("Beat")).toBeInTheDocument();
    expect(screen.getByText("Miss")).toBeInTheDocument();
    expect(screen.getByText("Consensus")).toBeInTheDocument();
  });

  it("renders nothing without actuals", () => {
    const { container } = render(<EpsChart actual={[]} estimate={ESTIMATE} />);
    expect(container.firstChild).toBeNull();
  });
});
