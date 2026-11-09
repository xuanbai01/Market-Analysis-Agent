/**
 * stored-list — the one place the app reads and writes the ticker
 * lists it keeps in localStorage (watchlist, recent).
 *
 * Every write announces itself with a window event, and
 * ``useStoredList`` subscribes to it through ``useSyncExternalStore``.
 * So when the star button on a symbol page adds a ticker, the sidebar
 * shows it on the same render — no re-reading on route change, no
 * per-component mirrors drifting apart. The browser's ``storage`` event
 * is also observed, so another open tab stays in step.
 *
 * Storage shape: a JSON ``string[]`` per key. A corrupt or unreadable
 * payload (bad JSON, private mode, quota) reads as an empty list.
 */
import { useMemo, useSyncExternalStore } from "react";

const CHANGE_EVENT = "market-agent:stored-list-change";

function readRaw(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function parseList(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((v): v is string => typeof v === "string");
  } catch {
    return [];
  }
}

/** Read the list stored under ``key``. */
export function readStoredList(key: string): string[] {
  return parseList(readRaw(key));
}

/** Replace the list stored under ``key`` and notify subscribers. */
export function writeStoredList(key: string, list: readonly string[]): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(list));
  } catch {
    // Quota / private mode — the write is lost; readers keep the old list.
    return;
  }
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGE_EVENT, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGE_EVENT, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/**
 * The list under ``key``, re-rendering whenever it changes.
 *
 * The store snapshot is the raw JSON string — strings compare by value,
 * so React only re-renders when the stored content actually differs.
 */
export function useStoredList(key: string): string[] {
  const raw = useSyncExternalStore(
    subscribe,
    () => readRaw(key),
    () => null,
  );
  return useMemo(() => parseList(raw), [raw]);
}
