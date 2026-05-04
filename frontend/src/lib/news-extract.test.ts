/**
 * news-extract tests (Phase 4.4.A).
 *
 * Pulls the News section's claims into the shape ``NewsList`` renders.
 * Each Claim from the backend's ``fetch_news`` carries:
 *   description = headline (verbatim)
 *   value       = sentiment string ("positive" | "neutral" | "negative")
 *   source.url  = article URL
 *   source.detail = "category=<bucket>" (one of EARNINGS / PRODUCT /
 *                   REGULATORY / M_AND_A / SUPPLY / STRATEGY / OTHER)
 *   source.fetched_at = article published_at ISO timestamp
 *   source.tool = "<provider>.news" (e.g. "newsapi.news")
 *
 * The extractor parses these into typed NewsItem records, dropping any
 * malformed entries (missing url, unknown sentiment, etc.) silently.
 */
import { describe, expect, it } from "vitest";

import { extractNewsItems } from "./news-extract";
import type { Claim, ClaimValue, Section } from "./schemas";

function claim(
  description: string,
  value: ClaimValue,
  url: string,
  detail: string,
  fetchedAt = "2026-05-03T14:00:00+00:00",
  tool = "newsapi.news",
): Claim {
  return {
    description,
    value,
    source: { tool, fetched_at: fetchedAt, url, detail },
    history: [],
  };
}

function section(claims: Claim[]): Section {
  return { title: "News", claims, summary: "", confidence: "medium" };
}

describe("extractNewsItems", () => {
  it("returns one NewsItem per Claim with category/sentiment parsed", () => {
    const out = extractNewsItems(
      section([
        claim(
          "Apple beats Q1 estimates",
          "positive",
          "https://example.com/aapl-q1",
          "category=earnings",
        ),
        claim(
          "iPhone 17 launches in September",
          "neutral",
          "https://example.com/iphone17",
          "category=product",
          "2026-05-02T10:00:00+00:00",
          "rss_yahoo.news",
        ),
      ]),
    );
    expect(out).toHaveLength(2);
    expect(out[0]).toEqual({
      title: "Apple beats Q1 estimates",
      url: "https://example.com/aapl-q1",
      sourceLabel: "newsapi",
      publishedAt: "2026-05-03T14:00:00+00:00",
      category: "earnings",
      sentiment: "positive",
    });
    expect(out[1].sourceLabel).toBe("rss_yahoo");
    expect(out[1].category).toBe("product");
  });

  it("returns an empty list when the section has no claims", () => {
    expect(extractNewsItems(section([]))).toEqual([]);
  });

  it("drops items missing a URL", () => {
    const c = claim(
      "Apple does something",
      "neutral",
      "https://example.com/x",
      "category=other",
    );
    // Stub away the url so the source is malformed.
    c.source = { ...c.source, url: undefined };
    const out = extractNewsItems(section([c]));
    expect(out).toEqual([]);
  });

  it("falls back to category=other when detail can't be parsed", () => {
    const out = extractNewsItems(
      section([
        claim(
          "Some headline",
          "neutral",
          "https://example.com/x",
          "weird-detail-format",
        ),
      ]),
    );
    expect(out).toHaveLength(1);
    expect(out[0].category).toBe("other");
  });

  it("falls back to sentiment=neutral when value is not a known string", () => {
    const out = extractNewsItems(
      section([
        claim("h", 42 as unknown as ClaimValue, "https://x.com", "category=other"),
      ]),
    );
    expect(out[0].sentiment).toBe("neutral");
  });
});
