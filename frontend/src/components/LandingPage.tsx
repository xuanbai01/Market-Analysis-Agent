/**
 * LandingPage — / route. Authenticated user's home.
 *
 * Phase 4.7 surface:
 *   1. Recent tickers grid — last-visited tickers as clickable cards
 *      (from localStorage). Hidden when empty.
 *   2. Watchlist grid — pinned tickers as clickable cards (from
 *      localStorage). Hidden when empty.
 *   3. Search bar — submit navigates to /symbol/:ticker (uppercased).
 *      ⌘K opens the SearchModal from anywhere; the inline form is
 *      preserved as the no-shortcut fallback + the form's input is
 *      what AppShell focuses when Search is clicked from the sidebar.
 *   4. Recent reports — PastReportsList driven by GET /v1/research.
 *
 * The recent + watchlist sections each render up to ~10 ticker cards
 * with no extra fetches — they're pure localStorage reads. The Past
 * Reports list below still drives the cached-report click-through
 * since it's the only surface that knows the report's confidence /
 * generated_at.
 */
import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { listResearchReports } from "../lib/api";
import { listRecent } from "../lib/recent";
import { ROUTES } from "../lib/routes";
import type { ResearchReportSummary } from "../lib/schemas";
import { listWatchlist } from "../lib/watchlist";
import { PastReportsList } from "./PastReportsList";

export function LandingPage() {
  const navigate = useNavigate();
  const [symbol, setSymbol] = useState("");

  const summariesQuery = useQuery({
    queryKey: ["past-reports"],
    queryFn: () => listResearchReports({ limit: 20 }),
    staleTime: 30_000,
  });

  // Read once on mount — both lists are localStorage-only and small,
  // and a fresh navigation re-mounts the page so we always see the
  // latest after a user visits a new ticker.
  const [recentTickers] = useState<string[]>(() => listRecent());
  const [watchlistTickers] = useState<string[]>(() => listWatchlist());

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = symbol.trim();
    if (!trimmed) return;
    navigate(ROUTES.symbol(trimmed));
  }

  function handleSelectPast(summary: ResearchReportSummary) {
    navigate(ROUTES.symbol(summary.symbol));
  }

  function handleTickerCardClick(ticker: string) {
    navigate(ROUTES.symbol(ticker));
  }

  return (
    <div className="mx-auto max-w-4xl px-8 py-16">
      <header className="mb-12 text-center">
        <p className="font-mono text-xs uppercase tracking-kicker text-strata-muted">
          Market Analysis Agent
        </p>
        <h1 className="mt-3 text-3xl font-semibold tracking-tight text-strata-hi">
          Research any ticker
        </h1>
        <p className="mt-2 text-sm text-strata-dim">
          Adaptive dashboards backed by free data and citation discipline.
        </p>
      </header>

      {recentTickers.length > 0 && (
        <section className="mb-10">
          <h2 className="mb-3 px-1 font-mono text-xs uppercase tracking-kicker text-strata-muted">
            Recent tickers
          </h2>
          <TickerGrid tickers={recentTickers} onSelect={handleTickerCardClick} />
        </section>
      )}

      {watchlistTickers.length > 0 && (
        <section className="mb-10">
          <h2 className="mb-3 px-1 font-mono text-xs uppercase tracking-kicker text-strata-muted">
            Watchlist
          </h2>
          <TickerGrid tickers={watchlistTickers} onSelect={handleTickerCardClick} />
        </section>
      )}

      <form onSubmit={handleSubmit} className="mb-12">
        <label htmlFor="landing-search" className="sr-only">
          Symbol or ticker
        </label>
        <div className="mx-auto flex max-w-xl items-center gap-3 rounded-xl border border-strata-border bg-strata-surface px-5 py-4 shadow-[0_24px_48px_-24px_rgba(0,0,0,0.6)] focus-within:border-strata-highlight">
          <span className="font-mono text-strata-highlight">⌕</span>
          <input
            id="landing-search"
            name="symbol-search"
            aria-label="Symbol or ticker"
            type="text"
            autoFocus
            autoComplete="off"
            placeholder="NVDA · try AAPL, MSFT, JPM"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="flex-1 bg-transparent font-mono text-sm uppercase tracking-wide text-strata-hi placeholder-strata-muted focus:outline-none"
          />
          <kbd className="rounded border border-strata-border px-1.5 py-0.5 font-mono text-[10px] text-strata-muted">
            ⏎
          </kbd>
        </div>
      </form>

      <div className="mx-auto max-w-xl">
        <PastReportsList
          summaries={summariesQuery.data ?? []}
          isLoading={summariesQuery.isPending}
          error={summariesQuery.error}
          onSelect={handleSelectPast}
        />
      </div>
    </div>
  );
}

interface TickerGridProps {
  tickers: string[];
  onSelect: (ticker: string) => void;
}

/** Grid of clickable ticker cards. Each card is tiny — ticker label
 *  only — keeping the surface fast to render and free of network
 *  fan-out. Future iteration can add per-card sparklines fed by the
 *  existing market-prices endpoint. */
function TickerGrid({ tickers, onSelect }: TickerGridProps) {
  return (
    <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4 md:grid-cols-5">
      {tickers.map((ticker) => (
        <li key={ticker}>
          <button
            type="button"
            onClick={() => onSelect(ticker)}
            data-card="ticker-card"
            className="w-full rounded-md border border-strata-border bg-strata-surface px-3 py-2 text-left transition hover:border-strata-highlight/40 hover:bg-strata-raise"
          >
            <span className="font-mono text-sm font-medium text-strata-hi">
              {ticker}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}
