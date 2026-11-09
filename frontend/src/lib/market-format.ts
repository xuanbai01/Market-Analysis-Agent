/**
 * Display rules for the market strip. A quote prints by its unit:
 * index points ("7,376.86"), a yield ("4.86%", moves in bps), or US
 * dollars ("$4,073.70"; large prices drop the cents: "$74,791").
 */
import type { MarketQuote, SentimentRating } from "./schemas";

export type Direction = "up" | "down" | "flat";

const LARGE_USD = 10_000;

function grouped(value: number, decimals: number): string {
  return value.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatQuotePrice(quote: Pick<MarketQuote, "price" | "unit">): string {
  const { price, unit } = quote;
  if (unit === "percent") return `${price.toFixed(2)}%`;
  if (unit === "usd") return `$${grouped(price, price >= LARGE_USD ? 0 : 2)}`;
  return grouped(price, 2);
}

/** The day's move: basis points for a yield, percent otherwise. */
export function formatQuoteChange(
  quote: Pick<MarketQuote, "change" | "change_percent" | "unit">,
): { text: string; direction: Direction } {
  if (quote.unit === "percent") {
    const bps = Math.round(quote.change * 100);
    return { text: `${bps > 0 ? "+" : ""}${bps} bps`, direction: directionOf(bps) };
  }
  const pct = Number(quote.change_percent.toFixed(2));
  return {
    text: `${pct > 0 ? "+" : ""}${pct.toFixed(2)}%`,
    direction: directionOf(pct),
  };
}

function directionOf(rounded: number): Direction {
  if (rounded > 0) return "up";
  if (rounded < 0) return "down";
  return "flat";
}

export const RATING_LABEL: Record<SentimentRating, string> = {
  extreme_fear: "Extreme fear",
  fear: "Fear",
  neutral: "Neutral",
  greed: "Greed",
  extreme_greed: "Extreme greed",
};

/** The rating bands on the 0–100 scale, as drawn on the meter. */
export const RATING_BANDS: { rating: SentimentRating; from: number; to: number }[] = [
  { rating: "extreme_fear", from: 0, to: 25 },
  { rating: "fear", from: 25, to: 45 },
  { rating: "neutral", from: 45, to: 56 },
  { rating: "greed", from: 56, to: 76 },
  { rating: "extreme_greed", from: 76, to: 100 },
];

/** "2026-11-06" → "Nov 6", read as a calendar date (no timezone shift). */
export function formatSessionDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  if (!y || !m || !d) return isoDate;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}
