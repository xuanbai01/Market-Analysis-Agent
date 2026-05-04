/**
 * QualityCard tests (Phase 4.2).
 *
 * Replaces ReportRenderer's Quality section. Layout:
 *
 *   header (kicker + ticker)
 *   3 MetricRings: ROE / ROIC / FCF margin
 *   MultiLine: gross / operating / FCF margins
 *   claims table — 6 default + "Show all 16" disclosure
 *
 * Pinned behaviors:
 *
 * 1. Renders 3 MetricRing primitives.
 * 2. Renders a MultiLine when at least 2 margin series have history.
 * 3. Renders 6 claim rows by default (the 6 default-display set).
 * 4. Clicking "Show all" expands to the full claim list.
 * 5. Renders the section's summary prose when present.
 * 6. Falls back gracefully when ring values are absent.
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render } from "@testing-library/react";

import { QualityCard } from "./QualityCard";
import type { Claim, ClaimHistoryPoint, ClaimValue, Section } from "../lib/schemas";

const HIST: ClaimHistoryPoint[] = [
  { period: "2024-Q1", value: 0.42 },
  { period: "2024-Q2", value: 0.45 },
  { period: "2024-Q3", value: 0.48 },
  { period: "2024-Q4", value: 0.51 },
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

const FULL_CLAIMS: Claim[] = [
  claim("Return on equity", 0.32),
  claim("Gross margin", 0.74, HIST),
  claim("Net profit margin", 0.55),
  claim("Gross margin, year-over-year change", 0.02),
  claim("Revenue per share", 50.2, HIST),
  claim("Gross profit per share", 37.1, HIST),
  claim("Operating income per share", 24.0, HIST),
  claim("Free cash flow per share", 21.0, HIST),
  claim("Operating cash flow per share", 25.5, HIST),
  claim("Operating margin", 0.48, HIST),
  claim("Free cash flow margin", 0.42, HIST),
  claim("Cash + short-term investments per share", 11.2, HIST),
  claim("Total debt per share", 4.1, HIST),
  claim("Total assets per share", 50.0, HIST),
  claim("Total liabilities per share", 12.0, HIST),
  claim("Return on invested capital (TTM)", 0.61, HIST),
];

describe("QualityCard", () => {
  it("renders 3 MetricRing primitives (ROE / ROIC / FCF margin)", () => {
    const { container } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS)} />,
    );
    const rings = container.querySelectorAll(
      "[data-testid='metric-ring']",
    );
    expect(rings.length).toBe(3);
  });

  it("renders a MultiLine when margin series have history", () => {
    const { container } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS)} />,
    );
    expect(
      container.querySelector("[data-testid='multi-line']"),
    ).not.toBeNull();
  });

  it("renders the 6 default claims by default (not all 16)", () => {
    const { container } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS)} />,
    );
    const rows = container.querySelectorAll("[data-row='quality-claim']");
    expect(rows.length).toBe(6);
  });

  it("renders all 16 claims after Show-all click", () => {
    const { container, getByRole } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS)} />,
    );
    const button = getByRole("button", { name: /show all/i });
    fireEvent.click(button);
    const rows = container.querySelectorAll("[data-row='quality-claim']");
    expect(rows.length).toBe(16);
  });

  it("collapses back to 6 claims after Show-fewer click", () => {
    const { container, getByRole } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS)} />,
    );
    const expand = getByRole("button", { name: /show all/i });
    fireEvent.click(expand);
    const collapse = getByRole("button", { name: /show fewer/i });
    fireEvent.click(collapse);
    const rows = container.querySelectorAll("[data-row='quality-claim']");
    expect(rows.length).toBe(6);
  });

  it("renders the summary prose when present", () => {
    const { getByText } = render(
      <QualityCard
        ticker="NVDA"
        section={section(
          FULL_CLAIMS,
          "Margins are expanding across the stack.",
        )}
      />,
    );
    expect(getByText("Margins are expanding across the stack.")).not.toBeNull();
  });

  it("renders without throwing when ring values are absent", () => {
    expect(() =>
      render(<QualityCard ticker="NVDA" section={section([])} />),
    ).not.toThrow();
  });

  it("hides the Show-all button when fewer than 7 claims are present", () => {
    const small = section(FULL_CLAIMS.slice(0, 5));
    const { queryByRole } = render(<QualityCard ticker="NVDA" section={small} />);
    expect(queryByRole("button", { name: /show all/i })).toBeNull();
  });

  // Phase 4.3.X / cosmetic backlog from PR #50: design calls for a
  // "MARGINS · 5Y" sub-kicker above the MultiLine with inline values
  // matching the legend chips ("● GM 74.0 · ● OM 48.0 · ● FCF 42.0").
  it("renders a MARGINS sub-kicker with inline GM/OM/FCF values", () => {
    const { container } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS)} />,
    );
    const subkicker = container.querySelector(
      "[data-testid='quality-margins-subkicker']",
    );
    expect(subkicker).not.toBeNull();
    const text = subkicker!.textContent ?? "";
    // Sub-kicker must label itself as MARGINS.
    expect(text.toUpperCase()).toMatch(/MARGINS/);
    // And carry the snapshot values from the matching FULL_CLAIMS:
    //   Gross margin = 0.74         → "74"
    //   Operating margin = 0.48     → "48"
    //   Free cash flow margin = 0.42 → "42"
    // Display goes through formatClaimValue so the rendered form is
    // "74.00%" etc.; assert the integer parts appear.
    expect(text).toMatch(/74/);
    expect(text).toMatch(/48/);
    expect(text).toMatch(/42/);
  });

  // Phase 4.4.B — per-card narrative strip at bottom of card body.
  it("renders the card_narrative strip when present", () => {
    const { getByTestId } = render(
      <QualityCard
        ticker="NVDA"
        section={section(
          FULL_CLAIMS,
          "Long broad summary.",
          "Trajectory positive, level positive. Margins stable.",
        )}
      />,
    );
    const strip = getByTestId("card-narrative");
    expect(strip.textContent).toContain("Trajectory positive");
  });

  it("hides the card_narrative strip when null", () => {
    const { queryByTestId } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS, "summary only")} />,
    );
    expect(queryByTestId("card-narrative")).toBeNull();
  });

  // ── Phase 4.5.B — distressed-mode ring color flip ────────────────

  it("colors the ROE ring red when ROE is negative", () => {
    const distressed: Claim[] = [
      claim("Return on equity", -0.62),
      claim("Return on invested capital (TTM)", 0.05),
      claim("Free cash flow margin", 0.10, HIST),
    ];
    const { container } = render(
      <QualityCard ticker="RIVN" section={section(distressed)} />,
    );
    // The ROE ring is the first MetricRing in the trio. Its accent
    // class flips to ``text-strata-neg`` so the eyebrow + arc both
    // render in the loss color.
    const rings = container.querySelectorAll("[data-testid='metric-ring']");
    const roeWrapper = rings[0]?.parentElement;
    expect(roeWrapper?.innerHTML ?? "").toMatch(/text-strata-neg/);
  });

  it("colors the ROIC ring red when ROIC TTM is negative", () => {
    const distressed: Claim[] = [
      claim("Return on equity", 0.05),
      claim("Return on invested capital (TTM)", -0.41),
      claim("Free cash flow margin", 0.10, HIST),
    ];
    const { container } = render(
      <QualityCard ticker="RIVN" section={section(distressed)} />,
    );
    const rings = container.querySelectorAll("[data-testid='metric-ring']");
    const roicWrapper = rings[1]?.parentElement;
    expect(roicWrapper?.innerHTML ?? "").toMatch(/text-strata-neg/);
  });

  it("colors the FCF margin ring red when FCF margin is negative", () => {
    const distressed: Claim[] = [
      claim("Return on equity", 0.05),
      claim("Return on invested capital (TTM)", 0.05),
      claim("Free cash flow margin", -0.52, HIST),
    ];
    const { container } = render(
      <QualityCard ticker="RIVN" section={section(distressed)} />,
    );
    const rings = container.querySelectorAll("[data-testid='metric-ring']");
    const fcfWrapper = rings[2]?.parentElement;
    expect(fcfWrapper?.innerHTML ?? "").toMatch(/text-strata-neg/);
  });

  it("keeps default ring colors when all values are non-negative", () => {
    const { container } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS)} />,
    );
    // FULL_CLAIMS has positive ROE/ROIC/FCF margin. None of the rings
    // should pick up the distressed accent. Assertion via "the rings
    // section's HTML doesn't contain the neg accent class anywhere".
    const ringSection = container.querySelector(".grid.grid-cols-3");
    expect(ringSection?.innerHTML ?? "").not.toMatch(/text-strata-neg/);
  });
});
