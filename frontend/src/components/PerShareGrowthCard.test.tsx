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

  // Phase 4.3.X / Bug 5: PerShareGrowthCard reads from the Quality
  // section, the same section QualityCard reads. Both rendering
  // ``section.summary`` produced visible duplication ("AAPL demonstrates
  // strong profitability metrics..." appearing verbatim in both cards).
  // The fix is to drop the narrative strip from PerShareGrowthCard
  // entirely — the multipliers ARE the message — and reintroduce
  // card-specific narratives in Phase 4.4.
  it("does NOT render the shared section summary prose", () => {
    const { queryByText } = render(
      <PerShareGrowthCard
        ticker="NVDA"
        section={section(FULL, "Per-share growth has compounded across the stack.")}
      />,
    );
    expect(
      queryByText(/per-share growth has compounded/i),
    ).toBeNull();
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

  // Phase 4.3.B.1 — CAGR annotations. Each multiplier pill grows a
  // sub-line showing the per-quarter compound growth rate over the
  // visible period. Adds vertical density so the card grows closer to
  // its row partner (ValuationCard) without changing the layout.
  // CAGR per period = multiplier^(1/n_periods) − 1, expressed as a %.

  it("renders a CAGR sub-line under each multiplier pill", () => {
    const { container } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(FULL)} />,
    );
    const pills = container.querySelectorAll("[data-pill='growth-multiplier']");
    expect(pills.length).toBe(5);
    // Every pill must have a CAGR annotation (data-attribute scoped).
    for (const pill of pills) {
      const cagr = pill.querySelector("[data-testid='growth-cagr']");
      expect(cagr).not.toBeNull();
    }
  });

  it("formats CAGR as a signed percent per quarter", () => {
    const { container } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(FULL)} />,
    );
    // HIST has 5 points: 10 → 62 (multiplier 6.2×). CAGR over 4 periods
    // = 6.2^(1/4) − 1 ≈ 0.578 ≈ 58% per quarter. Match the integer
    // part — the formatter chooses 0 or 1 decimal. Allow either form.
    const firstPillCagr = container
      .querySelector("[data-pill='growth-multiplier'] [data-testid='growth-cagr']");
    expect(firstPillCagr).not.toBeNull();
    expect(firstPillCagr!.textContent).toMatch(/\+?(57|58|59)/);
  });

  it("renders an em-dash for CAGR when the multiplier is null", () => {
    const partial: Claim[] = [
      claim("Revenue per share", null, []),
      claim("Gross profit per share", 43, HIST),
      claim("Operating income per share", 24, HIST),
      claim("Free cash flow per share", 21, HIST),
      claim("Operating cash flow per share", 25.5, HIST),
    ];
    const { container } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(partial)} />,
    );
    const pills = container.querySelectorAll("[data-pill='growth-multiplier']");
    const revPillCagr = pills[0].querySelector(
      "[data-testid='growth-cagr']",
    );
    expect(revPillCagr).not.toBeNull();
    expect(revPillCagr!.textContent).toContain("—");
  });
});
