/**
 * CashAndCapitalCard tests (Phase 4.3.A).
 *
 * Cross-section card. Top stack reads CapEx + SBC from Capital
 * Allocation; bottom stack reads Cash + Debt from Quality. Highlight
 * box at the bottom shows Net cash / share = (cash − debt latest).
 *
 * Pinned behaviors:
 *
 * 1. Renders 2 MultiLine SVGs when both stacks have data.
 * 2. Renders the Net cash / share value.
 * 3. Renders an em-dash when net cash can't be computed.
 * 4. Renders the highlight box in pos color when net cash > 0,
 *    neg color when < 0.
 * 5. Falls back to a single MultiLine when only one stack has data.
 * 6. Renders nothing-fancy fallback when both stacks are empty.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { CashAndCapitalCard } from "./CashAndCapitalCard";
import type { Claim, ClaimHistoryPoint, ClaimValue, Section } from "../lib/schemas";

const HIST: ClaimHistoryPoint[] = [
  { period: "2024-Q1", value: 1.0 },
  { period: "2024-Q2", value: 1.1 },
  { period: "2024-Q3", value: 1.2 },
  { period: "2024-Q4", value: 1.3 },
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

function section(title: string, claims: Claim[]): Section {
  return { title, claims, summary: "", confidence: "high" };
}

const CAP_ALLOC = section("Capital Allocation", [
  claim("Capital expenditure per share", 1.41, HIST),
  claim("Stock-based compensation per share", 1.51, HIST),
]);

const QUALITY = section("Quality", [
  claim("Cash + short-term investments per share", 26.84, HIST),
  claim("Total debt per share", 3.92, HIST),
]);

describe("CashAndCapitalCard", () => {
  it("renders 2 MultiLine SVGs when both stacks have data", () => {
    const { container } = render(
      <CashAndCapitalCard
        capAllocSection={CAP_ALLOC}
        qualitySection={QUALITY}
      />,
    );
    const charts = container.querySelectorAll("[data-testid='multi-line']");
    expect(charts.length).toBe(2);
  });

  it("renders the Net cash / share value when cash + debt are present", () => {
    const { getByText } = render(
      <CashAndCapitalCard
        capAllocSection={CAP_ALLOC}
        qualitySection={QUALITY}
      />,
    );
    // 26.84 - 3.92 = 22.92. Phase 4.3.X — net cash / share renders
    // with the $ prefix (unit hint "usd_per_share"); legacy heuristic
    // would've rendered "22.92" with no prefix.
    expect(getByText("$22.92")).not.toBeNull();
  });

  it("renders an em-dash when net cash can't be computed", () => {
    const noCash = section("Quality", [
      claim("Total debt per share", 3.92, HIST),
    ]);
    const { container } = render(
      <CashAndCapitalCard
        capAllocSection={CAP_ALLOC}
        qualitySection={noCash}
      />,
    );
    const highlight = container.querySelector(
      "[data-testid='net-cash-highlight']",
    );
    expect(highlight?.textContent).toContain("—");
  });

  it("colors the net-cash highlight as pos when value > 0", () => {
    const { container } = render(
      <CashAndCapitalCard
        capAllocSection={CAP_ALLOC}
        qualitySection={QUALITY}
      />,
    );
    const highlight = container.querySelector(
      "[data-testid='net-cash-highlight']",
    );
    expect(highlight?.getAttribute("data-sign")).toBe("pos");
  });

  it("colors the net-cash highlight as neg when value < 0", () => {
    const debtHeavy = section("Quality", [
      claim("Cash + short-term investments per share", 2.0),
      claim("Total debt per share", 10.5),
    ]);
    const { container } = render(
      <CashAndCapitalCard
        capAllocSection={CAP_ALLOC}
        qualitySection={debtHeavy}
      />,
    );
    const highlight = container.querySelector(
      "[data-testid='net-cash-highlight']",
    );
    expect(highlight?.getAttribute("data-sign")).toBe("neg");
  });

  it("falls back when no histories are present", () => {
    const empty = section("Capital Allocation", []);
    const emptyQ = section("Quality", []);
    const { container } = render(
      <CashAndCapitalCard
        capAllocSection={empty}
        qualitySection={emptyQ}
      />,
    );
    const charts = container.querySelectorAll("[data-testid='multi-line']");
    expect(charts.length).toBe(0);
  });

  it("does not throw when sections are undefined", () => {
    expect(() =>
      render(
        <CashAndCapitalCard
          capAllocSection={undefined}
          qualitySection={undefined}
        />,
      ),
    ).not.toThrow();
  });

  // ── Phase 4.5.B — runway tile + raise-needed annotation ──────────

  it("renders a runway stat tile when cash_runway_quarters is provided", () => {
    const { getByTestId } = render(
      <CashAndCapitalCard
        capAllocSection={CAP_ALLOC}
        qualitySection={QUALITY}
        runwayQuarters={4.5}
      />,
    );
    const tile = getByTestId("cash-runway-tile");
    expect(tile.textContent).toMatch(/runway/i);
    expect(tile.textContent).toMatch(/4\.5/);
  });

  it("includes 'raise likely needed' sub-line when runway < 6", () => {
    const { getByTestId } = render(
      <CashAndCapitalCard
        capAllocSection={CAP_ALLOC}
        qualitySection={QUALITY}
        runwayQuarters={4.5}
      />,
    );
    const tile = getByTestId("cash-runway-tile");
    expect(tile.textContent).toMatch(/raise likely needed/i);
  });

  it("omits 'raise likely needed' when runway >= 6", () => {
    const { getByTestId } = render(
      <CashAndCapitalCard
        capAllocSection={CAP_ALLOC}
        qualitySection={QUALITY}
        runwayQuarters={8.0}
      />,
    );
    const tile = getByTestId("cash-runway-tile");
    expect(tile.textContent).not.toMatch(/raise likely needed/i);
  });

  it("omits the runway tile when runwayQuarters is null", () => {
    const { queryByTestId } = render(
      <CashAndCapitalCard
        capAllocSection={CAP_ALLOC}
        qualitySection={QUALITY}
        runwayQuarters={null}
      />,
    );
    expect(queryByTestId("cash-runway-tile")).toBeNull();
  });

  it("omits the runway tile when the prop is undefined", () => {
    const { queryByTestId } = render(
      <CashAndCapitalCard
        capAllocSection={CAP_ALLOC}
        qualitySection={QUALITY}
      />,
    );
    expect(queryByTestId("cash-runway-tile")).toBeNull();
  });
});
