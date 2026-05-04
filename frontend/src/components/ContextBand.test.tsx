/**
 * ContextBand tests (Phase 4.4.A).
 *
 * Thin wrapper holding ``BusinessCard`` (left) + ``NewsList`` (right)
 * between the HeroCard and the row-2 grid. 2-col on lg, 1-col below.
 * Returns null when both children sections are absent so the grid
 * doesn't render an empty band.
 */
import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { ContextBand } from "./ContextBand";
import type { Claim, ClaimValue, Section } from "../lib/schemas";

function claim(description: string, value: ClaimValue): Claim {
  return {
    description,
    value,
    source: { tool: "test", fetched_at: "2026-05-04T01:00:00+00:00" },
    history: [],
  };
}

function newsClaim(
  title: string,
  sentiment: string,
  category: string,
): Claim {
  return {
    description: title,
    value: sentiment as ClaimValue,
    source: {
      tool: "newsapi.news",
      fetched_at: "2026-05-03T14:00:00+00:00",
      url: "https://example.com/x",
      detail: `category=${category}`,
    },
    history: [],
  };
}

function section(title: string, claims: Claim[]): Section {
  return { title, claims, summary: "", confidence: "medium" };
}

const BUSINESS = section("Business", [
  claim("Business description (from 10-K filing)", "Apple Inc. designs..."),
  claim("Headquarters location", "Cupertino, CA"),
  claim("Full-time employee count", 164_000),
]);

const NEWS = section("News", [
  newsClaim("Apple beats Q1", "positive", "earnings"),
  newsClaim("iPhone 17", "neutral", "product"),
]);

describe("ContextBand", () => {
  it("renders both BusinessCard and NewsList when both sections exist", () => {
    const { container } = render(
      <ContextBand
        ticker="AAPL"
        businessSection={BUSINESS}
        newsSection={NEWS}
      />,
    );
    expect(
      container.querySelector("[data-testid='context-band']"),
    ).not.toBeNull();
    // Business presence = the summary text shows.
    expect(container.textContent).toMatch(/Apple Inc\. designs/);
    // News presence = a news item row.
    expect(
      container.querySelector("[data-row='news-item']"),
    ).not.toBeNull();
  });

  it("returns null when both sections are absent", () => {
    const { container } = render(
      <ContextBand
        ticker="AAPL"
        businessSection={undefined}
        newsSection={undefined}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders only News when Business is absent", () => {
    const { container } = render(
      <ContextBand
        ticker="AAPL"
        businessSection={undefined}
        newsSection={NEWS}
      />,
    );
    expect(
      container.querySelector("[data-testid='context-band']"),
    ).not.toBeNull();
    expect(
      container.querySelector("[data-row='news-item']"),
    ).not.toBeNull();
  });
});
