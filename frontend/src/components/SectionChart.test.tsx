/**
 * SectionChart tests (Phase 3.3.B).
 *
 * The chart itself is opaque (Recharts internals); these tests pin the
 * external contract:
 *
 * 1. Renders an ``<svg>`` with ``data-testid='section-chart'`` when
 *    primary has at least 2 history points.
 * 2. Returns null on empty / single-point primary history (defense-
 *    in-depth — featuredClaim is the first gate, this is the second).
 * 3. Single-line variant (no secondary) renders one ``recharts-line``
 *    DOM marker; dual-line variant renders two.
 * 4. Misaligned secondary periods don't crash; the chart anchors on
 *    primary's period axis.
 *
 * We don't assert on tick labels, tooltips, or pixel layout — Recharts
 * is well-tested upstream and pinning those couples us to its DOM
 * conventions across versions.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import type { Claim, ClaimHistoryPoint } from "../lib/schemas";
import { SectionChart } from "./SectionChart";

function makeHistory(values: number[]): ClaimHistoryPoint[] {
  return values.map((v, i) => ({ period: `2024-Q${i + 1}`, value: v }));
}

function claim(history: ClaimHistoryPoint[], description = "Test metric"): Claim {
  const last = history[history.length - 1];
  return {
    description,
    value: last ? last.value : null,
    source: {
      tool: "yfinance.fundamentals",
      fetched_at: "2026-04-29T14:00:00+00:00",
    },
    history,
  };
}

describe("SectionChart", () => {
  it("renders an SVG when primary has 2+ history points", () => {
    const { container } = render(
      <SectionChart primary={claim(makeHistory([1, 2, 3, 4]))} />,
    );
    expect(
      container.querySelector("[data-testid='section-chart']"),
    ).not.toBeNull();
  });

  it("returns null when primary history is empty", () => {
    const { container } = render(<SectionChart primary={claim([])} />);
    expect(
      container.querySelector("[data-testid='section-chart']"),
    ).toBeNull();
  });

  it("returns null when primary history has only one point", () => {
    const { container } = render(
      <SectionChart primary={claim(makeHistory([1.5]))} />,
    );
    expect(
      container.querySelector("[data-testid='section-chart']"),
    ).toBeNull();
  });

  it("renders a single line when no secondary is provided", () => {
    const { container } = render(
      <SectionChart primary={claim(makeHistory([1, 2, 3, 4]))} />,
    );
    // Recharts renders each <Line /> with class ``recharts-line``.
    const lines = container.querySelectorAll(".recharts-line");
    expect(lines.length).toBe(1);
  });

  it("renders two lines when a secondary claim is provided", () => {
    const primary = claim(makeHistory([1.4, 1.53, 2.05, 2.18]), "EPS actual");
    const secondary = claim(
      makeHistory([1.35, 1.5, 2.0, 2.1]),
      "EPS estimate",
    );
    const { container } = render(
      <SectionChart primary={primary} secondary={secondary} />,
    );
    expect(container.querySelectorAll(".recharts-line").length).toBe(2);
  });

  it("renders without throwing when secondary periods don't align with primary", () => {
    const primary = claim(makeHistory([1, 2, 3, 4]));
    // Different period labels → secondary contributes no aligned values.
    const secondary: Claim = {
      description: "Secondary",
      value: 99,
      source: {
        tool: "x",
        fetched_at: "2026-04-29T14:00:00+00:00",
      },
      history: [
        { period: "2099-Q1", value: 99 },
        { period: "2099-Q2", value: 100 },
      ],
    };
    expect(() =>
      render(<SectionChart primary={primary} secondary={secondary} />),
    ).not.toThrow();
  });

  it("renders without throwing on a flat (constant) primary history", () => {
    expect(() =>
      render(<SectionChart primary={claim(makeHistory([5, 5, 5, 5]))} />),
    ).not.toThrow();
  });

  it("respects custom width and height on the SVG", () => {
    const { container } = render(
      <SectionChart
        primary={claim(makeHistory([1, 2, 3]))}
        width={400}
        height={160}
      />,
    );
    const svg = container.querySelector("[data-testid='section-chart']");
    // Recharts sets width/height attributes on its inner svg element.
    expect(svg?.getAttribute("width")).toBe("400");
    expect(svg?.getAttribute("height")).toBe("160");
  });
});
