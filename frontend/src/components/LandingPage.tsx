/**
 * LandingPage — / route. Authenticated user's home.
 *
 * Two parts:
 *   1. Search bar — submit navigates to /symbol/:ticker (uppercased)
 *   2. Recent reports — PastReportsList driven by GET /v1/research
 *
 * Phase 4.7 replaces the inline form with a `⌘K` modal + autocomplete.
 * Phase 4.4 will add a sector-level news feed below.
 */
import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";

import { listResearchReports } from "../lib/api";
import { ROUTES } from "../lib/routes";
import type { ResearchReportSummary } from "../lib/schemas";
import { PastReportsList } from "./PastReportsList";

export function LandingPage() {
  const navigate = useNavigate();
  const [symbol, setSymbol] = useState("");

  const summariesQuery = useQuery({
    queryKey: ["past-reports"],
    queryFn: () => listResearchReports({ limit: 20 }),
    staleTime: 30_000,
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = symbol.trim();
    if (!trimmed) return;
    navigate(ROUTES.symbol(trimmed));
  }

  function handleSelectPast(summary: ResearchReportSummary) {
    navigate(ROUTES.symbol(summary.symbol));
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
