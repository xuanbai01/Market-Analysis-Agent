/**
 * news-extract — pulls the News section's claims into typed NewsItem
 * records. Phase 4.4.A.
 *
 * Each Claim from the backend's ``fetch_news`` carries:
 *
 *   description        = headline (verbatim)
 *   value              = sentiment string ("positive"/"neutral"/"negative")
 *   source.url         = article URL
 *   source.detail      = "category=<bucket>"
 *   source.fetched_at  = published_at ISO timestamp
 *   source.tool        = "<provider>.news" (e.g. "newsapi.news")
 *
 * The extractor parses these into typed records; malformed entries
 * (missing url, unknown sentiment, etc.) fall back to
 * ``category=other / sentiment=neutral`` so the dashboard still
 * renders something rather than silently dropping the headline.
 */
import type { Section } from "./schemas";

export type NewsCategory =
  | "earnings"
  | "product"
  | "regulatory"
  | "m_and_a"
  | "supply"
  | "strategy"
  | "other";

export const NEWS_CATEGORIES: readonly NewsCategory[] = [
  "earnings",
  "product",
  "regulatory",
  "m_and_a",
  "supply",
  "strategy",
  "other",
];

export type NewsSentiment = "positive" | "neutral" | "negative";

export interface NewsItem {
  title: string;
  url: string;
  /** Human-friendly source label, e.g. "newsapi" or "rss_yahoo".
   *  Derived from ``source.tool`` by stripping the trailing ".news". */
  sourceLabel: string;
  publishedAt: string;
  category: NewsCategory;
  sentiment: NewsSentiment;
}

const KNOWN_CATEGORIES = new Set<NewsCategory>(NEWS_CATEGORIES);
const KNOWN_SENTIMENTS = new Set<NewsSentiment>([
  "positive",
  "neutral",
  "negative",
]);

function parseCategoryFromDetail(detail: string | null | undefined): NewsCategory {
  if (!detail) return "other";
  // Format is `"category=<bucket>"` from the backend. We do a simple
  // regex match instead of a full URL-style parse so a future
  // additional metadata field doesn't break this.
  const match = /category=([a-z_]+)/i.exec(detail);
  if (!match) return "other";
  const candidate = match[1].toLowerCase() as NewsCategory;
  return KNOWN_CATEGORIES.has(candidate) ? candidate : "other";
}

function parseSentimentFromValue(value: unknown): NewsSentiment {
  if (typeof value === "string") {
    const lower = value.toLowerCase() as NewsSentiment;
    if (KNOWN_SENTIMENTS.has(lower)) return lower;
  }
  return "neutral";
}

function deriveSourceLabel(tool: string): string {
  // "newsapi.news" → "newsapi"; "rss_yahoo.news" → "rss_yahoo";
  // bare "newsapi" passes through unchanged.
  return tool.endsWith(".news") ? tool.slice(0, -".news".length) : tool;
}

/**
 * Returns one ``NewsItem`` per Claim that carries a valid article
 * URL. Malformed claims (no URL) are dropped silently.
 */
export function extractNewsItems(section: Section): NewsItem[] {
  const out: NewsItem[] = [];
  for (const claim of section.claims) {
    const url = claim.source.url;
    if (typeof url !== "string" || !url.trim()) continue;
    out.push({
      title: claim.description,
      url,
      sourceLabel: deriveSourceLabel(claim.source.tool),
      publishedAt: claim.source.fetched_at,
      category: parseCategoryFromDetail(claim.source.detail),
      sentiment: parseSentimentFromValue(claim.value),
    });
  }
  return out;
}

