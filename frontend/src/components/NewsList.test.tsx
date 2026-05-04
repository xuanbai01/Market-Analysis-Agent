/**
 * NewsList tests (Phase 4.4.A).
 *
 * Reads News-section claims via ``extractNewsItems``, renders a header
 * eyebrow with item count, a filter pill row (ALL / EARNINGS / PRODUCT
 * / REGULATORY / M&A / SUPPLY / STRATEGY / OTHER), and a list of items
 * with title/source/date + category chip + sentiment dot. Default
 * shows 5 items; "View N more" expands.
 */
import { describe, expect, it } from "vitest";
import { fireEvent, render } from "@testing-library/react";

import { NewsList } from "./NewsList";
import type { Claim, ClaimValue, Section } from "../lib/schemas";

function newsClaim(
  title: string,
  sentiment: "positive" | "neutral" | "negative",
  category: string,
  url = "https://example.com/x",
  fetchedAt = "2026-05-03T14:00:00+00:00",
): Claim {
  return {
    description: title,
    value: sentiment as ClaimValue,
    source: {
      tool: "newsapi.news",
      fetched_at: fetchedAt,
      url,
      detail: `category=${category}`,
    },
    history: [],
  };
}

function section(claims: Claim[]): Section {
  return { title: "News", claims, summary: "", confidence: "medium" };
}

const SEVEN_ITEMS: Claim[] = [
  newsClaim("Apple beats Q1 estimates", "positive", "earnings"),
  newsClaim("iPhone 17 launches in September", "neutral", "product"),
  newsClaim("EU opens antitrust probe", "negative", "regulatory"),
  newsClaim("Apple acquires AI startup", "positive", "m_and_a"),
  newsClaim("TSMC tariff threat", "negative", "supply"),
  newsClaim("App Store strategy update", "neutral", "strategy"),
  newsClaim("Misc news 7", "neutral", "other"),
];

describe("NewsList", () => {
  it("renders the header with an item count", () => {
    const { container } = render(<NewsList section={section(SEVEN_ITEMS)} />);
    const header = container.querySelector("[data-testid='news-header']");
    expect(header).not.toBeNull();
    expect(header!.textContent).toMatch(/7\s+items?/i);
  });

  it("renders a row of category filter pills (all + 7 categories)", () => {
    const { container } = render(<NewsList section={section(SEVEN_ITEMS)} />);
    const pills = container.querySelectorAll("[data-pill='news-filter']");
    // ALL + 7 buckets = 8 pills.
    expect(pills.length).toBe(8);
  });

  it("renders 5 items by default", () => {
    const { container } = render(<NewsList section={section(SEVEN_ITEMS)} />);
    const rows = container.querySelectorAll("[data-row='news-item']");
    expect(rows.length).toBe(5);
  });

  it("expands to all items when 'View more' is clicked", () => {
    const { container, getByRole } = render(
      <NewsList section={section(SEVEN_ITEMS)} />,
    );
    const button = getByRole("button", { name: /view\s+\d+\s+more/i });
    fireEvent.click(button);
    const rows = container.querySelectorAll("[data-row='news-item']");
    expect(rows.length).toBe(7);
  });

  it("filters to one category when its pill is clicked", () => {
    const { container, getByRole } = render(
      <NewsList section={section(SEVEN_ITEMS)} />,
    );
    fireEvent.click(getByRole("button", { name: /^earnings$/i }));
    const rows = container.querySelectorAll("[data-row='news-item']");
    // Only the "Apple beats Q1 estimates" item is in the earnings bucket.
    expect(rows.length).toBe(1);
    expect(rows[0].textContent).toMatch(/Apple beats Q1/);
  });

  it("renders a fallback when the section has no items", () => {
    const { getByText } = render(<NewsList section={section([])} />);
    expect(getByText(/no recent news/i)).not.toBeNull();
  });

  it("each item carries its source label, sentiment, and a clickable link", () => {
    const { container } = render(
      <NewsList section={section([SEVEN_ITEMS[0]])} />,
    );
    const row = container.querySelector("[data-row='news-item']");
    expect(row).not.toBeNull();
    const link = row!.querySelector("a");
    expect(link).not.toBeNull();
    expect(link!.getAttribute("href")).toMatch(/^https?:\/\//);
    // Sentiment dot under a stable testid.
    expect(
      row!.querySelector("[data-testid='news-sentiment']"),
    ).not.toBeNull();
  });
});
