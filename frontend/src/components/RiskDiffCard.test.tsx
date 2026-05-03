/**
 * RiskDiffCard tests (Phase 4.3.A).
 *
 * Renders an inline horizontal bar chart of the 4 risk-diff aggregate
 * counts (added / removed / kept / char_delta) plus a one-sentence
 * prose summary. 4.3.B will swap the aggregate bars for per-category
 * bars when the Haiku categorizer lands; until then this card uses
 * the data already produced by extract_10k_risks_diff.
 *
 * Pinned behaviors:
 *
 * 1. Renders an SVG with data-testid='risk-diff-bars' when bars are
 *    available.
 * 2. Renders one bar per row (added / removed / kept / char delta).
 * 3. Renders the prose summary with the right framing word.
 * 4. Renders a fallback when the diff is unavailable.
 * 5. Honors the "shrank" framing when net delta < 0.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { RiskDiffCard } from "./RiskDiffCard";
import type { Claim, ClaimValue, Section } from "../lib/schemas";

function claim(description: string, value: ClaimValue): Claim {
  return {
    description,
    value,
    source: { tool: "sec.ten_k_risks_diff", fetched_at: "2026-05-03T14:00:00+00:00" },
    history: [],
  };
}

function section(claims: Claim[]): Section {
  return { title: "Risk Factors", claims, summary: "", confidence: "high" };
}

const FULL: Claim[] = [
  claim("Newly added risk paragraphs vs prior 10-K", 12),
  claim("Risk paragraphs dropped vs prior 10-K", 3),
  claim("Risk paragraphs kept (carryover)", 47),
  claim("Item 1A char delta vs prior 10-K", 8421),
];

describe("RiskDiffCard", () => {
  it("renders an SVG with data-testid='risk-diff-bars' when bars are available", () => {
    const { container } = render(<RiskDiffCard section={section(FULL)} />);
    expect(
      container.querySelector("[data-testid='risk-diff-bars']"),
    ).not.toBeNull();
  });

  it("renders one bar row per metric (4 rows)", () => {
    const { container } = render(<RiskDiffCard section={section(FULL)} />);
    const rows = container.querySelectorAll("[data-row='risk-diff-bar']");
    expect(rows.length).toBe(4);
  });

  it("renders the prose summary with 'expanded' framing for net delta > 0", () => {
    const { getByText } = render(<RiskDiffCard section={section(FULL)} />);
    expect(getByText(/expanded/i)).not.toBeNull();
    expect(getByText(/\+9/)).not.toBeNull();
  });

  it("uses 'shrank' framing for net delta < 0", () => {
    const shrank = section([
      claim("Newly added risk paragraphs vs prior 10-K", 1),
      claim("Risk paragraphs dropped vs prior 10-K", 5),
      claim("Risk paragraphs kept (carryover)", 50),
      claim("Item 1A char delta vs prior 10-K", -2400),
    ]);
    const { getByText } = render(<RiskDiffCard section={shrank} />);
    expect(getByText(/shrank/i)).not.toBeNull();
  });

  it("uses 'stable' framing for net delta = 0", () => {
    const stable = section([
      claim("Newly added risk paragraphs vs prior 10-K", 3),
      claim("Risk paragraphs dropped vs prior 10-K", 3),
      claim("Risk paragraphs kept (carryover)", 50),
      claim("Item 1A char delta vs prior 10-K", 100),
    ]);
    const { getByText } = render(<RiskDiffCard section={stable} />);
    expect(getByText(/stable/i)).not.toBeNull();
  });

  it("renders a fallback when the diff is unavailable", () => {
    const { container, getByText } = render(
      <RiskDiffCard section={section([])} />,
    );
    expect(
      container.querySelector("[data-testid='risk-diff-bars']"),
    ).toBeNull();
    expect(getByText(/risk diff unavailable/i)).not.toBeNull();
  });

  // Phase 4.3.B: when per-category claims are present, the card swaps
  // the aggregate 4-bar chart for a per-category bar chart driven by
  // ``extractRiskCategoryDeltas``. Aggregates fall back when no
  // per-category claims exist (pre-4.3.B reports + stable disclosures).

  it("renders per-category bars when category-delta claims are present", () => {
    const withCats = section([
      ...FULL,
      claim("AI / regulatory risk paragraph delta vs prior 10-K", 3),
      claim("Cybersecurity risk paragraph delta vs prior 10-K", -2),
      claim("Macro risk paragraph delta vs prior 10-K", 1),
    ]);
    const { container } = render(<RiskDiffCard section={withCats} />);
    const catBars = container.querySelectorAll(
      "[data-testid='risk-category-bars'] [data-row='risk-category-bar']",
    );
    expect(catBars.length).toBe(3);
    // Aggregate chart is hidden when per-category bars take its place.
    expect(
      container.querySelector("[data-testid='risk-diff-bars']"),
    ).toBeNull();
  });

  it("falls back to aggregate bars when no per-category claims exist", () => {
    const { container } = render(<RiskDiffCard section={section(FULL)} />);
    expect(
      container.querySelector("[data-testid='risk-category-bars']"),
    ).toBeNull();
    expect(
      container.querySelector("[data-testid='risk-diff-bars']"),
    ).not.toBeNull();
  });

  it("labels each per-category bar with the human-readable category name", () => {
    const withCats = section([
      ...FULL,
      claim("Supply concentration risk paragraph delta vs prior 10-K", 4),
    ]);
    const { container } = render(<RiskDiffCard section={withCats} />);
    const labels = Array.from(
      container.querySelectorAll(
        "[data-row='risk-category-bar']",
      ),
    ).map((row) => row.textContent ?? "");
    // The "Supply concentration" label appears (case-insensitive,
    // whatever the card chooses for display).
    expect(labels.some((t) => /supply/i.test(t))).toBe(true);
  });
});
