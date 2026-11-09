/**
 * sidebar — the pure rules behind the app sidebar, kept out of the
 * component so each one is tested on its own.
 *
 * The sidebar answers two questions: "where can I go?" (Home, Compare,
 * Search) and "what was I looking at?" (Watchlist, Recent). These
 * helpers decide what Compare opens, which recent tickers are worth a
 * row, and whether the user wants the sidebar collapsed.
 */
import { POPULAR_TICKERS } from "./popular-tickers";
import { ROUTES } from "./routes";

/** Recent rows shown in the sidebar (the stored list keeps more). */
export const SIDEBAR_RECENT_MAX = 5;

const COLLAPSED_KEY = "market-agent.sidebar-collapsed";

export interface ComparePair {
  a: string;
  b: string;
}

/**
 * The pair the sidebar's Compare link opens.
 *
 * ``a`` is the ticker on screen when there is one, else the most recent,
 * else the first watched. ``b`` is the next distinct ticker from recent,
 * then watchlist, then the popular list — so Compare always has two
 * names, and the user's own tickers win over defaults.
 */
export function comparePair(
  currentTicker: string | null,
  recent: readonly string[],
  watchlist: readonly string[],
): ComparePair {
  const candidates = [
    ...(currentTicker ? [currentTicker] : []),
    ...recent,
    ...watchlist,
    ...POPULAR_TICKERS,
  ];
  const a = candidates[0];
  const b = candidates.find((t) => t !== a) ?? a;
  return { a, b };
}

export function compareHref({ a, b }: ComparePair): string {
  const params = new URLSearchParams({ a, b });
  return `${ROUTES.compare}?${params.toString()}`;
}

/** The pair already on screen at /compare?a=X&b=Y, if both are set. */
export function pairFromSearch(search: string): ComparePair | null {
  const params = new URLSearchParams(search);
  const a = params.get("a")?.trim().toUpperCase();
  const b = params.get("b")?.trim().toUpperCase();
  return a && b ? { a, b } : null;
}

/**
 * Recent tickers worth a sidebar row: the most recent few that are not
 * already listed under Watchlist (one row per ticker, never two).
 */
export function sidebarRecent(
  recent: readonly string[],
  watchlist: readonly string[],
  max: number = SIDEBAR_RECENT_MAX,
): string[] {
  const watched = new Set(watchlist);
  return recent.filter((t) => !watched.has(t)).slice(0, max);
}

export function readSidebarCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

export function writeSidebarCollapsed(collapsed: boolean): void {
  try {
    if (collapsed) window.localStorage.setItem(COLLAPSED_KEY, "1");
    else window.localStorage.removeItem(COLLAPSED_KEY);
  } catch {
    // Private mode — the preference just doesn't persist.
  }
}

/** "⌘K" on Apple platforms, "Ctrl K" elsewhere — matches AppShell's listener. */
export function searchShortcutLabel(
  userAgent: string = typeof navigator === "undefined" ? "" : navigator.userAgent,
): string {
  return /Mac|iPhone|iPad/.test(userAgent) ? "⌘K" : "Ctrl K";
}
