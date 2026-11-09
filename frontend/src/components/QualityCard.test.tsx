/**
 * QualityCard tests (Phase 4.2).
 *
 * Replaces ReportRenderer's Quality section. Layout:
 *
 *   header (kicker + ticker)
 *   3 headline stat tiles: ROE / ROIC / FCF margin
 *   MultiLine: gross / operating / FCF margins
 *   claims table — 6 default + "Show all 16" disclosure
 *
 * Pinned behaviors:
 *
 * 1. Renders 3 headline stat tiles, each naming its basis.
 * 2. Renders a MultiLine when at least 2 margin series have history.
 * 3. Renders 6 claim rows by default (the 6 default-display set).
 * 4. Clicking "Show all" expands to the full claim list.
 * 5. Renders the section's summary prose when present.
 * 6. Falls back gracefully when headline values are absent.
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
  it("renders 3 headline stat tiles (ROE / ROIC / FCF margin) with their basis", () => {
    const { container } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS)} />,
    );
    const stats = Array.from(container.querySelectorAll("[data-testid='quality-stat']"));
    expect(stats).toHaveLength(3);
    expect(stats[0].textContent).toContain("ROE");
    expect(stats[0].textContent).toContain("32.00%");
    expect(stats[0].textContent).toContain("trailing 12 months");
    expect(stats[2].textContent).toContain("latest quarter");
    // No meter graphic and no unsourced ranking.
    expect(container.querySelector("[data-testid='metric-ring']")).toBeNull();
    expect(container.textContent).not.toMatch(/decile/i);
  });

  it("renders a MultiLine when margin series have history", () => {
    const { container } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS)} />,
    );
    expect(
      container.querySelector("[data-testid='multi-line']"),
    ).not.toBeNull();
  });

  // 2026-11 dogfood #8/#10 — the margins chart reads as percentages on a
  // labelled axis, and trend cells state their change.
  it("labels the margins chart's value axis in percent", () => {
    const { container } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS)} />,
    );
    const ticks = Array.from(
      container.querySelectorAll("[data-testid='multi-line-y-tick']"),
    ).map((t) => t.textContent);
    expect(ticks).toContain("0%");
  });

  it("states each claim's change in the trend column", () => {
    const { container } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS)} />,
    );
    expect(
      container.querySelectorAll("[data-testid='trend-delta']").length,
    ).toBeGreaterThan(0);
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

  it("renders without throwing when headline values are absent", () => {
    expect(() =>
      render(<QualityCard ticker="NVDA" section={section([])} />),
    ).not.toThrow();
  });

  it("hides the Show-all button when fewer than 7 claims are present", () => {
    const small = section(FULL_CLAIMS.slice(0, 5));
    const { queryByRole } = render(<QualityCard ticker="NVDA" section={small} />);
    expect(queryByRole("button", { name: /show all/i })).toBeNull();
  });

  // 2026-11 chart audit: the sub-kicker used to repeat snapshot values,
  // but gross margin's snapshot is trailing-12-month while the line ends
  // at the latest quarter — two "GM" numbers on one card. It now only
  // says what the chart plots; the end labels carry the values.
  it("labels the margins chart as quarterly without repeating values", () => {
    const { container } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS)} />,
    );
    const text =
      container.querySelector("[data-testid='quality-margins-subkicker']")?.textContent ?? "";
    expect(text).toMatch(/margins by quarter/i);
    expect(text).not.toMatch(/74/);
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

  // ── Phase 4.5.B — negative headline values read as losses ─────────

  it("marks each negative headline value as a loss", () => {
    const distressed: Claim[] = [
      claim("Return on equity", -0.62),
      claim("Return on invested capital (TTM)", 0.05),
      claim("Free cash flow margin", -0.52, HIST),
    ];
    const { container } = render(
      <QualityCard ticker="RIVN" section={section(distressed)} />,
    );
    const flags = Array.from(container.querySelectorAll("[data-testid='quality-stat']")).map((s) =>
      s.getAttribute("data-negative"),
    );
    expect(flags).toEqual(["true", "false", "true"]);
    const roe = container.querySelectorAll("[data-testid='quality-stat']")[0];
    expect(roe.innerHTML).toMatch(/text-strata-neg/);
  });

  it("keeps default colors when all values are non-negative", () => {
    const { container } = render(
      <QualityCard ticker="NVDA" section={section(FULL_CLAIMS)} />,
    );
    const stats = container.querySelector("[data-testid='quality-headline-stats']");
    expect(stats?.innerHTML ?? "").not.toMatch(/text-strata-neg/);
  });
});
