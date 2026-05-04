/**
 * EarningsCard tests (Phase 4.1).
 *
 * Replaces the Earnings section's claim-table rendering with a richer
 * card: 20-quarter EPS bars (actual vs estimate), beat-rate headline,
 * next-print date, 3 stat tiles below.
 *
 * Behaviors pinned:
 * 1. Headline shows "X of N beat consensus" using last_20q.beat_count
 *    when available.
 * 2. Next-print date renders when next.report_date claim exists.
 * 3. EpsBars rendered with the eps_actual and eps_estimate histories.
 * 4. Three stat tiles below: Beat rate, Surprise μ, EPS TTM.
 * 5. Falls back gracefully when claims are missing (renders what's
 *    available, omits what isn't, never crashes).
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { EarningsCard } from "./EarningsCard";
import type { Section } from "../lib/schemas";

function fakeEarningsSection(): Section {
  return {
    title: "Earnings",
    summary: "Latest beat consensus.",
    confidence: "high",
    claims: [
      {
        description: "Most recent earnings report date",
        value: "2024-10-31",
        source: { tool: "yfinance.earnings", fetched_at: "2026-05-02T14:00:00+00:00" },
        history: [],
      },
      {
        description: "Reported EPS (latest quarter)",
        value: 2.18,
        source: { tool: "yfinance.earnings", fetched_at: "2026-05-02T14:00:00+00:00" },
        history: Array.from({ length: 20 }, (_, i) => ({
          period: `2020-Q${(i % 4) + 1}`,
          value: 1 + i * 0.1,
        })),
      },
      {
        description: "Consensus EPS estimate (latest quarter, going in)",
        value: 2.1,
        source: { tool: "yfinance.earnings", fetched_at: "2026-05-02T14:00:00+00:00" },
        history: Array.from({ length: 20 }, (_, i) => ({
          period: `2020-Q${(i % 4) + 1}`,
          value: 0.95 + i * 0.1,
        })),
      },
      {
        description: "EPS surprise % (latest quarter)",
        value: 3.8,
        source: { tool: "yfinance.earnings", fetched_at: "2026-05-02T14:00:00+00:00" },
        history: [],
      },
      {
        description: "Next earnings report date (expected)",
        value: "2026-05-21",
        source: { tool: "yfinance.earnings", fetched_at: "2026-05-02T14:00:00+00:00" },
        history: [],
      },
      {
        description: "Number of EPS beats over the last 20 quarters (or fewer if history is shorter)",
        value: 17,
        source: { tool: "yfinance.earnings", fetched_at: "2026-05-02T14:00:00+00:00" },
        history: [],
      },
      {
        description: "Average EPS surprise (%) over the last 20 quarters of history",
        value: 8.2,
        source: { tool: "yfinance.earnings", fetched_at: "2026-05-02T14:00:00+00:00" },
        history: [],
      },
    ],
  };
}

describe("EarningsCard", () => {
  it("renders 'X of N beat consensus' headline from last_20q.beat_count", () => {
    render(<EarningsCard section={fakeEarningsSection()} />);
    expect(screen.getByText(/17 of 20 beat/i)).toBeInTheDocument();
  });

  it("renders the next-print date", () => {
    render(<EarningsCard section={fakeEarningsSection()} />);
    expect(screen.getByText(/2026-05-21/)).toBeInTheDocument();
  });

  it("embeds EpsBars with the actual + estimate histories", () => {
    const { container } = render(
      <EarningsCard section={fakeEarningsSection()} />,
    );
    expect(
      container.querySelector("[data-testid='eps-bars']"),
    ).not.toBeNull();
  });

  it("renders 3 stat tiles (Beat rate, Surprise μ, EPS TTM)", () => {
    render(<EarningsCard section={fakeEarningsSection()} />);
    expect(screen.getByText(/beat rate/i)).toBeInTheDocument();
    // Surprise μ tile — match the μ glyph specifically so the search
    // doesn't collide with the RecentPrints header which also says
    // "actual · estimate · surprise" (Phase 4.3.B.1).
    expect(screen.getByText(/surprise\s*μ/i)).toBeInTheDocument();
    expect(screen.getByText(/eps ttm/i)).toBeInTheDocument();
  });

  it("computes beat rate as count / 20", () => {
    render(<EarningsCard section={fakeEarningsSection()} />);
    // 17 / 20 = 85%
    expect(screen.getByText(/85\s*%/)).toBeInTheDocument();
  });

  it("renders without throwing on a section with no claims", () => {
    const empty: Section = {
      title: "Earnings",
      summary: "",
      confidence: "low",
      claims: [],
    };
    expect(() => render(<EarningsCard section={empty} />)).not.toThrow();
  });

  it("renders without throwing on a section missing the EPS history claims", () => {
    const partial: Section = {
      title: "Earnings",
      summary: "",
      confidence: "medium",
      claims: [
        {
          description: "Next earnings report date (expected)",
          value: "2026-05-21",
          source: { tool: "yfinance.earnings", fetched_at: "2026-05-02T14:00:00+00:00" },
          history: [],
        },
      ],
    };
    expect(() => render(<EarningsCard section={partial} />)).not.toThrow();
  });

  // Phase 4.3.B.1 — RecentPrints sub-table. Adds substantive content
  // below the 3 stat tiles so the card grows closer to its row partner
  // (QualityCard, ~700-1200 px). Mini-table shows the last 4 quarters'
  // period · actual · estimate · surprise %; surprise color-coded.

  it("renders a RecentPrints mini-table with the last 4 quarters", () => {
    const { container } = render(
      <EarningsCard section={fakeEarningsSection()} />,
    );
    const table = container.querySelector("[data-testid='recent-prints']");
    expect(table).not.toBeNull();
    // 4 rows below the header.
    const rows = container.querySelectorAll(
      "[data-testid='recent-prints'] [data-row='recent-print']",
    );
    expect(rows.length).toBe(4);
  });

  it("RecentPrints renders period + actual + estimate + surprise per row", () => {
    const { container } = render(
      <EarningsCard section={fakeEarningsSection()} />,
    );
    const lastRow = container.querySelectorAll(
      "[data-testid='recent-prints'] [data-row='recent-print']",
    )[3]; // most recent
    expect(lastRow).toBeTruthy();
    const text = lastRow.textContent ?? "";
    // The fixture's history index 19 is the latest: actual = 1 + 19*0.1 = 2.9,
    // estimate = 0.95 + 19*0.1 = 2.85, surprise = (2.9-2.85)/2.85 ≈ 1.75%
    // → "+1.8%" with one-decimal rounding.
    expect(text).toMatch(/2\.90/); // actual
    expect(text).toMatch(/2\.85/); // estimate
    // Surprise rendered as a signed percent (one-decimal precision).
    expect(text).toMatch(/\+?1\.[678]\s*%/);
  });

  it("RecentPrints is hidden when the section has no EPS history", () => {
    const noHistory: Section = {
      title: "Earnings",
      summary: "",
      confidence: "low",
      claims: [
        {
          description: "Next earnings report date (expected)",
          value: "2026-05-21",
          source: { tool: "yfinance.earnings", fetched_at: "2026-05-02T14:00:00+00:00" },
          history: [],
        },
      ],
    };
    const { container } = render(<EarningsCard section={noHistory} />);
    expect(container.querySelector("[data-testid='recent-prints']")).toBeNull();
  });

  // Phase 4.4.B — per-card narrative strip.
  it("renders the card_narrative strip when present", () => {
    const sec = fakeEarningsSection();
    sec.card_narrative = "Loss is narrowing. EPS climbed steadily over 20Q.";
    const { getByTestId } = render(<EarningsCard section={sec} />);
    expect(getByTestId("card-narrative").textContent).toContain(
      "Loss is narrowing.",
    );
  });

  it("hides the card_narrative strip when null", () => {
    const sec = fakeEarningsSection();
    sec.card_narrative = null;
    const { queryByTestId } = render(<EarningsCard section={sec} />);
    expect(queryByTestId("card-narrative")).toBeNull();
  });
});
