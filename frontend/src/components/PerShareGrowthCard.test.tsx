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

function section(
  claims: Claim[],
  summary = "",
  cardNarrative: string | null = null,
): Section {
  return {
    title: "Quality",
    claims,
    summary,
    confidence: "high",
    card_narrative: cardNarrative,
  };
}

const FULL: Claim[] = [
  claim("Revenue per share", 62, HIST),
  claim("Gross profit per share", 43, HIST),
  claim("Operating income per share", 24, HIST),
  claim("Free cash flow per share", 21, HIST),
  claim("Operating cash flow per share", 25.5, HIST),
];

describe("PerShareGrowthCard", () => {
  // 2026-11 dogfood #8: one chart of five lines rebased to the first
  // quarter had no axis, no baseline and invented curves. Now: actual
  // $/share in two panels (income vs cash flow) on one shared scale.
  it("renders an income panel and a cash-flow panel", () => {
    const { getByTestId } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(FULL)} />,
    );
    const income = getByTestId("per-share-panel-income");
    const cash = getByTestId("per-share-panel-cashflow");
    expect(income.querySelector("[data-testid='multi-line']")).not.toBeNull();
    expect(cash.querySelector("[data-testid='multi-line']")).not.toBeNull();
    expect(income.querySelectorAll("path[data-series-line]")).toHaveLength(3);
    expect(cash.querySelectorAll("path[data-series-line]")).toHaveLength(2);
  });

  it("plots dollars per share on one shared, labelled scale", () => {
    const { getByTestId } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(FULL)} />,
    );
    const ticksOf = (id: string) =>
      Array.from(
        getByTestId(id).querySelectorAll("[data-testid='multi-line-y-tick']"),
      ).map((t) => t.textContent);
    const incomeTicks = ticksOf("per-share-panel-income");
    expect(incomeTicks).toContain("$0");
    expect(incomeTicks.every((t) => t?.startsWith("$"))).toBe(true);
    expect(ticksOf("per-share-panel-cashflow")).toEqual(incomeTicks);
  });

  it("labels each line's latest $/share value", () => {
    const { getByTestId } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(FULL)} />,
    );
    const labels = Array.from(
      getByTestId("per-share-panel-income").querySelectorAll(
        "[data-testid='multi-line-end-label']",
      ),
    ).map((l) => l.textContent);
    expect(labels).toContain("Rev $62.00");
  });

  it("no longer describes the chart as rebased", () => {
    const { container } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(FULL)} />,
    );
    expect(container.textContent).not.toMatch(/rebased/i);
    expect(container.textContent).toMatch(/\$ \/ share/i);
  });

  it("renders 5 change pills", () => {
    const { container } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(FULL)} />,
    );
    expect(container.querySelectorAll("[data-pill='growth-change']")).toHaveLength(5);
    // The multiplier and per-quarter rate are gone.
    expect(container.textContent).not.toMatch(/×|\/ Q/);
  });

  it("states the change since the first point when no year-earlier quarter exists", () => {
    const { container } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(FULL)} />,
    );
    const pill = container.querySelector("[data-pill='growth-change']");
    // 10 → 62: +520%, since Q1 '21.
    expect(pill?.textContent).toContain("+520%");
    expect(pill?.textContent).toContain("since Q1 '21");
  });

  it("labels year-over-year changes once below the pills", () => {
    const yoy: ClaimHistoryPoint[] = [
      { period: "2025-Q3", value: 2.8 },
      { period: "2025-Q4", value: 2.7 },
      { period: "2026-Q1", value: 2.85 },
      { period: "2026-Q2", value: 3.05 },
      { period: "2026-Q3", value: 3.1 },
    ];
    const { container } = render(
      <PerShareGrowthCard
        ticker="KO"
        section={section([claim("Revenue per share", 3.1, yoy), claim("Gross profit per share", 1.9, yoy)])}
      />,
    );
    const pill = container.querySelector("[data-pill='growth-change']");
    expect(pill?.textContent).toContain("+10.7%");
    expect(pill?.textContent).toContain("YoY");
    expect(container.textContent).toContain("YoY: Q3 '26 vs Q3 '25");
  });

  it("renders an em-dash in pills without enough history", () => {
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
    const pills = Array.from(container.querySelectorAll("[data-pill='growth-change']"));
    expect(pills.filter((p) => p.textContent?.includes("—"))).toHaveLength(4);
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

  // Phase 4.4.B — per-card narrative strip. Restores the bottom prose
  // surface that 4.3.X removed (it duplicated Quality's section.summary
  // since this card reads from Quality too); the new field is
  // card-specific so the duplication is gone.
  it("renders the card_narrative strip when present", () => {
    const { getByTestId } = render(
      <PerShareGrowthCard
        ticker="NVDA"
        section={section(
          FULL,
          "",
          "Revenue compounds; profit doesn't. Top line up 8.7×.",
        )}
      />,
    );
    expect(getByTestId("card-narrative").textContent).toContain(
      "Revenue compounds",
    );
  });

  it("hides the card_narrative strip when null", () => {
    const { queryByTestId } = render(
      <PerShareGrowthCard ticker="NVDA" section={section(FULL)} />,
    );
    expect(queryByTestId("card-narrative")).toBeNull();
  });
});
