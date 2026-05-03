/**
 * PerShareGrowthCard tests (Phase 4.3.A).
 *
 * Wraps the extractor + MultiLine primitive to render the
 * per-share-growth row card. Pinned behaviors:
 *
 * 1. Renders a MultiLine SVG when at least 2 series have rebased history.
 * 2. Renders 5 multiplier pills.
 * 3. Renders an em-dash in pills whose multiplier is null.
 * 4. Renders the section's summary prose when present.
 * 5. Returns a fallback message when no series can be rebased.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { PerShareGrowthCard } from "./PerShareGrowthCard";
import type { Claim, ClaimHistoryPoint, ClaimValue, Section } from "../lib/schemas";

const HIST: ClaimHistoryPoint[] = [
  { period: "2021-Q1", value: 10 },
  { period: "2021-Q2", value: 12 },
  { period: "2021-Q3", value: 15 },
  { period: "2022-Q1", value: 25 },
  { period: "2022-Q4", value: 62 },
];

function claim(
  description: string,
  value: ClaimValue,
  history: ClaimHistoryPoint[] = [],
): Claim {
  return {
    description,
    value,
    source: { tool: "yfinance.fundamentals", fetched_at: "2026-05-03T14:00:00+00:00" },
    history,
  };
}

function section(claims: Claim[], summary = ""): Section {
  return { title: "Quality", claims, summary, confidence: "high" };
}

const FULL: Claim[] = [
  claim("Revenue per share", 62, HIST),
  claim("Gross profit per share", 43, HIST),
  claim("Operating income per share", 24, HIST),
  claim("Free cash flow per share", 21, HIST),
  claim("Operating cash flow per share", 25.5, HIST),
];

describe("PerShareGrowthCard", () => {
  it("renders a MultiLine SVG when series have rebased history", () => {
    const { container } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(FULL)} />,
    );
    expect(
      container.querySelector("[data-testid='multi-line']"),
    ).not.toBeNull();
  });

  it("renders 5 multiplier pills", () => {
    const { container } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(FULL)} />,
    );
    const pills = container.querySelectorAll("[data-pill='growth-multiplier']");
    expect(pills.length).toBe(5);
  });

  it("renders the multiplier value formatted with × suffix", () => {
    const { getAllByText } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(FULL)} />,
    );
    // 62 / 10 = 6.2 → "6.2×". Test fixture uses the same HIST for
    // every series so multiple pills share the value; assert at
    // least one matches.
    expect(getAllByText("6.2×").length).toBeGreaterThan(0);
  });

  it("renders an em-dash in pills whose multiplier is null", () => {
    const partial: Claim[] = [
      claim("Revenue per share", 62, HIST),
      claim("Gross profit per share", null, []),
      claim("Operating income per share", null, []),
      claim("Free cash flow per share", null, []),
      claim("Operating cash flow per share", null, []),
    ];
    const { container } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(partial)} />,
    );
    const pills = container.querySelectorAll("[data-pill='growth-multiplier']");
    // 4 of 5 pills should show the em-dash.
    const emDashCount = Array.from(pills).filter((p) =>
      p.textContent?.includes("—"),
    ).length;
    expect(emDashCount).toBe(4);
  });

  it("renders the section summary prose when present", () => {
    const { getByText } = render(
      <PerShareGrowthCard
        ticker="NVDA"
        section={section(FULL, "Per-share growth has compounded across the stack.")}
      />,
    );
    expect(
      getByText(/per-share growth has compounded/i),
    ).not.toBeNull();
  });

  it("renders a fallback when no series can be rebased", () => {
    const { container, getByText } = render(
      <PerShareGrowthCard ticker="NVDA" section={section([])} />,
    );
    expect(
      container.querySelector("[data-testid='multi-line']"),
    ).toBeNull();
    expect(getByText(/per-share growth history/i)).not.toBeNull();
  });

  it("does not throw when section is undefined-safe", () => {
    expect(() =>
      render(<PerShareGrowthCard ticker="NVDA" section={section([])} />),
    ).not.toThrow();
  });
});
