/**
 * watchlist — tickers the user starred. Phase 4.7; live updates 2026-11.
 *
 * Written by the star button on /symbol/:ticker and the sidebar's
 * remove button; read by the sidebar's Watchlist section and the
 * search modal. ``useWatchlist`` re-renders on every change, wherever
 * it came from (see stored-list.ts).
 *
 * Storage shape: a JSON ``string[]`` of uppercased tickers under
 * ``market-agent.watchlist``, in the order they were added.
 */
import { readStoredList, useStoredList, writeStoredList } from "./stored-list";

const STORAGE_KEY = "market-agent.watchlist";

/** Return the current watchlist as an array of uppercased tickers. */
export function listWatchlist(): string[] {
  return readStoredList(STORAGE_KEY);
}

/** The watchlist, kept current across components and tabs. */
export function useWatchlist(): string[] {
  return useStoredList(STORAGE_KEY);
}

/** True when the ticker is in the watchlist (case-insensitive). */
export function isWatched(ticker: string): boolean {
  return listWatchlist().includes(ticker.toUpperCase());
}

/** Add a ticker. No-op when already present. Returns the new list. */
export function addToWatchlist(ticker: string): string[] {
  const normalized = ticker.toUpperCase();
  const current = listWatchlist();
  if (current.includes(normalized)) return current;
  const next = [...current, normalized];
  writeStoredList(STORAGE_KEY, next);
  return next;
}

/** Remove a ticker. No-op when absent. Returns the new list. */
export function removeFromWatchlist(ticker: string): string[] {
  const normalized = ticker.toUpperCase();
  const current = listWatchlist();
  const next = current.filter((t) => t !== normalized);
  if (next.length === current.length) return current;
  writeStoredList(STORAGE_KEY, next);
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
