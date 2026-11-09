/**
 * recent — most-recently-opened tickers. Phase 4.7; live updates 2026-11.
 *
 * SymbolDetailPage pushes a ticker once its report loads (so typos and
 * 404s never land here); the sidebar's Recent section and the search
 * modal read it. ``useRecent`` re-renders on every change.
 *
 * Storage shape: a JSON ``string[]`` of uppercased tickers under
 * ``market-agent.recent``, most recent first, capped at RECENT_MAX.
 */
import { readStoredList, useStoredList, writeStoredList } from "./stored-list";

const STORAGE_KEY = "market-agent.recent";

/** Maximum entries retained. The 11th push drops the oldest. */
export const RECENT_MAX = 10;

/** Return the recent list as an array of uppercased tickers, most-recent first. */
export function listRecent(): string[] {
  return readStoredList(STORAGE_KEY);
}

/** The recent list, kept current across components and tabs. */
export function useRecent(): string[] {
  return useStoredList(STORAGE_KEY);
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
  const current = listRecent();
  if (current[0] === normalized) return current;
  const next = [normalized, ...current.filter((t) => t !== normalized)].slice(
    0,
    RECENT_MAX,
  );
  writeStoredList(STORAGE_KEY, next);
  return next;
}

/** Forget every recent ticker. */
export function clearRecent(): void {
  writeStoredList(STORAGE_KEY, []);
}
