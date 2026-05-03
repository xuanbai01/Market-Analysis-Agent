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

  // Phase 4.3.B.1 — risk-diff bar SVG was hardcoded to 360 px width
  // and overflowed the narrow row-4 column (1/3 of viewport ~360 px
  // before padding), pushing the value labels outside the card. The
  // SVG width is now "100%" with viewBox preserving the internal coords.
  it("renders the risk-diff bars SVG at responsive width", () => {
    const { container } = render(<RiskDiffCard section={section(FULL)} />);
    const svg = container.querySelector("[data-testid='risk-diff-bars']");
    expect(svg?.getAttribute("width")).toBe("100%");
    // viewBox preserves the internal layout dims so labels stay
    // anchored at the right edge of the chart's coordinate system.
    expect(svg?.getAttribute("viewBox")).toMatch(/^0 0 \d+ \d+$/);
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
});
