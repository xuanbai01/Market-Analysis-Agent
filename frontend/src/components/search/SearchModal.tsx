/**
 * SearchModal — Phase 4.7. Triggered by ⌘K (or Ctrl+K) from anywhere
 * in the app.
 *
 * Filterable input over the union of:
 *   - recent tickers (front)
 *   - watchlist tickers (middle)
 *   - POPULAR_TICKERS curated list (back, deduped against the others)
 *
 * Submit (Enter) → onSelect(uppercased input). The caller is
 * responsible for navigating; this component is router-agnostic so
 * it tests cleanly without MemoryRouter.
 *
 * Esc closes via onClose.
 *
 * Lazy-loaded by App.tsx so the modal's tree (~3-4 KB gz) only ships
 * on first ⌘K, not in the main bundle.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import { listRecent } from "../../lib/recent";
import { listWatchlist } from "../../lib/watchlist";
import { POPULAR_TICKERS } from "../../lib/popular-tickers";

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onSelect: (ticker: string) => void;
}

interface Suggestion {
  ticker: string;
  source: "recent" | "watchlist" | "popular";
}

function buildSuggestions(): Suggestion[] {
  const recent = listRecent();
  const watchlist = listWatchlist();

  const seen = new Set<string>();
  const out: Suggestion[] = [];

  for (const t of recent) {
    if (seen.has(t)) continue;
    seen.add(t);
    out.push({ ticker: t, source: "recent" });
  }
  for (const t of watchlist) {
    if (seen.has(t)) continue;
    seen.add(t);
    out.push({ ticker: t, source: "watchlist" });
  }
  for (const t of POPULAR_TICKERS) {
    if (seen.has(t)) continue;
    seen.add(t);
    out.push({ ticker: t, source: "popular" });
  }
  return out;
}

function filterSuggestions(all: Suggestion[], query: string): Suggestion[] {
  const q = query.trim().toUpperCase();
  if (!q) return all;
  return all.filter((s) => s.ticker.includes(q));
}

function sourceLabel(source: Suggestion["source"]): string {
  if (source === "recent") return "Recent";
  if (source === "watchlist") return "Watchlist";
  return "Popular";
}

export function SearchModal({ isOpen, onClose, onSelect }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [query, setQuery] = useState("");

  // Build the suggestion union when the modal opens. Recompute when
  // localStorage changes between mounts is handled implicitly — this
  // memo only re-runs when isOpen flips, which is the entry point.
  const suggestions = useMemo<Suggestion[]>(() => {
    if (!isOpen) return [];
    return buildSuggestions();
  }, [isOpen]);

  // Reset query + autofocus on open.
  useEffect(() => {
    if (!isOpen) return;
    setQuery("");
    // Focus on the next tick so the input is mounted.
    const id = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [isOpen]);

  if (!isOpen) return null;

  const filtered = filterSuggestions(suggestions, query);

  function handleKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const trimmed = query.trim().toUpperCase();
      if (!trimmed) return;
      onSelect(trimmed);
      return;
    }
  }

  function handleSelect(ticker: string) {
    onSelect(ticker);
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Ticker search"
      className="fixed inset-0 z-50 flex items-start justify-center bg-strata-canvas/80 px-4 pt-24"
      onClick={onClose}
    >
      <div
        className="w-full max-w-lg rounded-xl border border-strata-border bg-strata-surface shadow-[0_24px_60px_-12px_rgba(0,0,0,0.6)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-strata-line px-5 py-4">
          <span className="font-mono text-strata-highlight">⌕</span>
          <input
            ref={inputRef}
            type="text"
            placeholder="Search by ticker (e.g. AAPL)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            aria-label="Ticker search input"
            className="flex-1 bg-transparent font-mono text-sm uppercase tracking-wide text-strata-hi placeholder-strata-muted focus:outline-none"
          />
          <kbd className="rounded border border-strata-border px-1.5 py-0.5 font-mono text-[10px] text-strata-muted">
            Esc
          </kbd>
        </div>
        <ul className="max-h-80 overflow-y-auto py-2">
          {filtered.length === 0 && (
            <li className="px-5 py-2 text-xs text-strata-dim">
              No matches. Press Enter to load &quot;{query.trim().toUpperCase() || "—"}&quot; anyway.
            </li>
          )}
          {filtered.map((s) => (
            <li key={`${s.source}:${s.ticker}`}>
              <button
                type="button"
                onClick={() => handleSelect(s.ticker)}
                className="flex w-full items-center justify-between gap-3 px-5 py-2 text-left transition hover:bg-strata-raise"
              >
                <span className="font-mono text-sm text-strata-hi">{s.ticker}</span>
                <span className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
                  {sourceLabel(s.source)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default SearchModal;
