/**
 * recent — localStorage-backed MRU list of last-visited tickers.
 * Phase 4.7.
 *
 * SymbolDetailPage pushes onto this on report-resolved; the sidebar
 * shows a count badge; the SearchModal + LandingPage surface recent
 * tickers inline.
 *
 * Storage shape: a plain JSON ``string[]`` of uppercased tickers under
 * ``market-agent.recent``. Front of the array = most recent. Cap at
 * RECENT_MAX so the list stays bounded; oldest entries drop off when
 * the cap is hit.
 *
 * Same defensive posture as watchlist.ts — corrupt payloads → [].
 */

const STORAGE_KEY = "market-agent.recent";

/** Maximum entries retained. The 11th push drops the oldest. */
export const RECENT_MAX = 10;

function read(): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((v): v is string => typeof v === "string");
  } catch {
    return [];
  }
}

function write(list: string[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    // see watchlist.ts
  }
}

/** Return the recent list as an array of uppercased tickers, most-recent first. */
export function listRecent(): string[] {
  return read();
}

/**
 * Push a ticker to the front. Removes any prior occurrence so the
 * ticker only appears once and is now the most recent. Caps the list
 * at ``RECENT_MAX``; oldest entries drop off the back.
 *
 * Returns the new list.
 */
export function pushRecent(ticker: string): string[] {
  const normalized = ticker.toUpperCase();
  const current = read();
  const dedup = current.filter((t) => t !== normalized);
  const next = [normalized, ...dedup].slice(0, RECENT_MAX);
  write(next);
  return next;
}
