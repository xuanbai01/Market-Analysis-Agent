/**
 * MacroPanel tests (Phase 4.3.A).
 *
 * Vertical stack of mini area-charts, one per FRED series in the
 * resolved sector's curated list. Each panel: kicker label + current
 * value badge + LineChart with areaFill.
 *
 * Pinned behaviors:
 *
 * 1. Renders one LineChart per series.
 * 2. Renders the series label and the current value with units.
 * 3. Renders a fallback when no series have data (FRED key unset / new
 *    sector / cached pre-3.2.F report).
 * 4. Renders the section's summary prose when present.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { MacroPanel } from "./MacroPanel";
import type { Claim, ClaimHistoryPoint, ClaimValue, Section } from "../lib/schemas";

const RATE_HIST: ClaimHistoryPoint[] = [
  { period: "2024-01", value: 4.5 },
  { period: "2024-02", value: 4.3 },
  { period: "2024-03", value: 4.2 },
  { period: "2024-04", value: 4.1 },
];

const CPI_HIST: ClaimHistoryPoint[] = [
  { period: "2024-01", value: 3.4 },
  { period: "2024-02", value: 3.2 },
  { period: "2024-03", value: 3.0 },
  { period: "2024-04", value: 2.8 },
];

function claim(
  description: string,
  value: ClaimValue,
  history: ClaimHistoryPoint[] = [],
): Claim {
  return {
    description,
    value,
    source: { tool: "fred.macro", fetched_at: "2026-05-03T14:00:00+00:00" },
    history,
  };
}

function section(
  claims: Claim[],
  summary = "",
  cardNarrative: string | null = null,
): Section {
  return {
    title: "Macro",
    claims,
    summary,
    confidence: "high",
    card_narrative: cardNarrative,
  };
}

const FULL: Claim[] = [
  claim("10Y Treasury yield (latest observation)", 4.1, RATE_HIST),
  claim("10Y Treasury yield observation date", "2024-04-01"),
  claim("Consumer price index (latest observation)", 2.8, CPI_HIST),
  claim("Consumer price index observation date", "2024-04-01"),
];

describe("MacroPanel", () => {
  it("renders one LineChart per series with usable data", () => {
    const { container } = render(<MacroPanel section={section(FULL)} />);
    const charts = container.querySelectorAll("[data-testid='line-chart']");
    expect(charts.length).toBe(2);
  });

  it("renders each series's label", () => {
    const { getByText } = render(<MacroPanel section={section(FULL)} />);
    expect(getByText(/10Y Treasury yield/)).not.toBeNull();
    expect(getByText(/Consumer price index/)).not.toBeNull();
  });

  it("renders each series's latest value", () => {
    const { container } = render(<MacroPanel section={section(FULL)} />);
    const text = container.textContent ?? "";
    expect(text).toMatch(/4\.1/);
    expect(text).toMatch(/2\.8/);
  });

  it("renders the section summary prose when present", () => {
    const { getByText } = render(
      <MacroPanel
        section={section(
          FULL,
          "Disinflation continues; rates trending down from peak.",
        )}
      />,
    );
    expect(getByText(/disinflation continues/i)).not.toBeNull();
  });

  it("renders a fallback when no series have data", () => {
    const { container, getByText } = render(
      <MacroPanel section={section([])} />,
    );
    const charts = container.querySelectorAll("[data-testid='line-chart']");
    expect(charts.length).toBe(0);
    expect(getByText(/macro context unavailable/i)).not.toBeNull();
  });

  // Phase 4.4.B — per-card narrative strip.
  it("renders the card_narrative strip when present", () => {
    const sec = section(
      FULL,
      "",
      "Disinflation continues. 10Y has compressed 43 bps from peak.",
    );
    const { getByTestId } = render(<MacroPanel section={sec} />);
    expect(getByTestId("card-narrative").textContent).toContain(
      "Disinflation continues.",
    );
  });

  it("hides the card_narrative strip when null", () => {
    const { queryByTestId } = render(
      <MacroPanel section={section(FULL)} />,
    );
    expect(queryByTestId("card-narrative")).toBeNull();
  });
});
