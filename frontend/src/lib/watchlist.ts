/**
 * watchlist — localStorage-backed list of tickers the user wants to
 * track. Phase 4.7.
 *
 * Pure helpers: no React, no fetch. The sidebar reads ``listWatchlist``
 * for its count badge; the WatchlistButton on /symbol/:ticker writes
 * via toggleWatchlist; the SearchModal surfaces watchlist tickers
 * inline alongside recents.
 *
 * Storage shape: a plain JSON ``string[]`` of uppercased tickers under
 * ``market-agent.watchlist``. Order is insertion-order (most-recently-
 * added at the back). Corrupt payloads are treated as empty rather
 * than crashing the app.
 */

const STORAGE_KEY = "market-agent.watchlist";

function read(): string[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    // Defensive: drop non-string entries silently.
    return parsed.filter((v): v is string => typeof v === "string");
  } catch {
    // Corrupt JSON or quota / private-mode error — treat as empty.
    return [];
  }
}

function write(list: string[]): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
  } catch {
    // Quota / private-mode — silent. Same posture as auth.ts.
  }
}

/** Return the current watchlist as an array of uppercased tickers. */
export function listWatchlist(): string[] {
  return read();
}

/** True when the ticker is in the watchlist (case-insensitive). */
export function isWatched(ticker: string): boolean {
  const normalized = ticker.toUpperCase();
  return read().includes(normalized);
}

/** Add a ticker. No-op when already present. Returns the new list. */
export function addToWatchlist(ticker: string): string[] {
  const normalized = ticker.toUpperCase();
  const current = read();
  if (current.includes(normalized)) return current;
  const next = [...current, normalized];
  write(next);
  return next;
}

/** Remove a ticker. No-op when absent. Returns the new list. */
export function removeFromWatchlist(ticker: string): string[] {
  const normalized = ticker.toUpperCase();
  const current = read();
  const next = current.filter((t) => t !== normalized);
  if (next.length === current.length) return current;
  write(next);
  return next;
}

/** Flip the watchlist state. Returns the new isWatched value. */
export function toggleWatchlist(ticker: string): boolean {
  if (isWatched(ticker)) {
    removeFromWatchlist(ticker);
    return false;
  }
  addToWatchlist(ticker);
  return true;
}
