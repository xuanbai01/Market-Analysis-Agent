/**
 * Curated list of popular tickers for the SearchModal's default
 * suggestions. Phase 4.7.
 *
 * Frontend-only — there's no backend ticker-search endpoint yet
 * (revisit in 4.7.B if dogfood signals it's missed). The user can
 * type any ticker and submit; this list is just a starting point
 * when their recent + watchlist sets are empty.
 *
 * Ordered roughly by sector + cap: megacap tech first, then financial,
 * defensive, industrial, consumer, energy. Twelve names — enough to
 * fill the modal without crowding.
 */

export const POPULAR_TICKERS: readonly string[] = [
  "NVDA",
  "AAPL",
  "MSFT",
  "GOOGL",
  "AMZN",
  "META",
  "TSLA",
  "AVGO",
  "JPM",
  "JNJ",
  "WMT",
  "COST",
] as const;
