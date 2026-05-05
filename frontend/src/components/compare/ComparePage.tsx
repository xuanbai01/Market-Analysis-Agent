/**
 * ComparePage — /compare?a=NVDA&b=AVGO. Phase 4.6.A.
 *
 * Two-ticker side-by-side dashboard. Reuses the per-card primitives
 * across two reports. Lazy-loaded as a single chunk by App.tsx so the
 * main bundle pays only ~0.5 KB for the route entry.
 *
 * Behavior:
 *   - Reads ?a + ?b from the URL, uppercases both.
 *   - Missing either param → redirect to landing.
 *   - Fires both fetchResearchReport calls in parallel via useQueries.
 *   - Renders CompareHero (with per-side HeaderPills), CompareMetricRow
 *     for Valuation + Quality, CompareMarginOverlay, CompareGrowthOverlay,
 *     CompareRiskDiff, and CompareFooter.
 *   - Swap button mutates the URL (?a, ?b exchange).
 *   - Add-ticker button is rendered but disabled — the search modal
 *     lands in 4.7.
 *
 * Phase 4.6.B may add an LLM compare narrative ("NVDA's op margin
 * overtook AVGO's in Q2-23"). Not in 4.6.A.
 */
import { useEffect } from "react";
import { useQueries } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";

import { ApiError, fetchResearchReport } from "../../lib/api";
import { clearStoredToken } from "../../lib/auth";
import {
  extractCompareHeroData,
  extractCompareQualityMetrics,
  extractCompareValuationMetrics,
} from "../../lib/compare-extract";
import { ROUTES } from "../../lib/routes";
import {
  HEALTHY_LAYOUT_SIGNALS,
  type LayoutSignals,
  type ResearchReport,
} from "../../lib/schemas";
import { ErrorBanner } from "../ErrorBanner";
import { LoadingState } from "../LoadingState";
import { CompareFooter } from "./CompareFooter";
import { CompareGrowthOverlay } from "./CompareGrowthOverlay";
import { CompareHero } from "./CompareHero";
import { CompareMarginOverlay } from "./CompareMarginOverlay";
import { CompareMetricRow } from "./CompareMetricRow";
import { CompareRiskDiff } from "./CompareRiskDiff";

function readTickers(params: URLSearchParams): { a: string | null; b: string | null } {
  const a = params.get("a")?.trim().toUpperCase() || null;
  const b = params.get("b")?.trim().toUpperCase() || null;
  return { a, b };
}

export function ComparePage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { a: tickerA, b: tickerB } = readTickers(params);

  // Missing either param — redirect to landing in an effect (returning
  // <Navigate> directly would force a remount on every param-less render
  // and obscure the redirect intent).
  useEffect(() => {
    if (!tickerA || !tickerB) {
      navigate(ROUTES.landing, { replace: true });
    }
  }, [tickerA, tickerB, navigate]);

  const reports = useQueries({
    queries: [tickerA, tickerB].map((ticker) => ({
      queryKey: ["report", ticker, "full"],
      queryFn: () => fetchResearchReport(ticker as string, { focus: "full" as const }),
      enabled: Boolean(ticker),
      staleTime: 60_000,
    })),
  });

  // Centralized 401 — clear token + bounce to login. Same pattern
  // SymbolDetailPage uses for the single-report fetch.
  useEffect(() => {
    const authError = reports.find(
      (r) => r.error instanceof ApiError && (r.error as ApiError).status === 401,
    );
    if (authError) {
      clearStoredToken();
      navigate(ROUTES.login, { replace: true });
    }
  }, [reports, navigate]);

  function handleSwap() {
    if (!tickerA || !tickerB) return;
    setParams({ a: tickerB, b: tickerA }, { replace: false });
  }

  // Until both reports are ready (or we've redirected away), render a
  // skeleton instead of half-populated cards.
  if (!tickerA || !tickerB) return null;

  const aQuery = reports[0];
  const bQuery = reports[1];

  const isPending = aQuery.isPending || bQuery.isPending;
  const hardError = [aQuery.error, bQuery.error].find(
    (e) => e && !(e instanceof ApiError && (e as ApiError).status === 401),
  );

  if (hardError) {
    return (
      <div className="mx-auto w-full max-w-screen-2xl px-6 py-8 lg:px-8 xl:px-10">
        <ErrorBanner error={hardError as Error} />
      </div>
    );
  }

  if (isPending || !aQuery.data || !bQuery.data) {
    return <LoadingState symbol={`${tickerA} / ${tickerB}`} />;
  }

  return (
    <ComparePageBody
      reportA={aQuery.data}
      reportB={bQuery.data}
      onSwap={handleSwap}
    />
  );
}

interface BodyProps {
  reportA: ResearchReport;
  reportB: ResearchReport;
  onSwap: () => void;
}

function ComparePageBody({ reportA, reportB, onSwap }: BodyProps) {
  const heroA = extractCompareHeroData(reportA);
  const heroB = extractCompareHeroData(reportB);
  const signalsA: LayoutSignals = reportA.layout_signals ?? HEALTHY_LAYOUT_SIGNALS;
  const signalsB: LayoutSignals = reportB.layout_signals ?? HEALTHY_LAYOUT_SIGNALS;
  const valuationCells = extractCompareValuationMetrics(reportA, reportB);
  const qualityCells = extractCompareQualityMetrics(reportA, reportB);

  return (
    <div
      data-testid="compare-container"
      className="mx-auto w-full max-w-screen-2xl px-6 py-8 lg:px-8 xl:px-10"
    >
      <div className="mb-6 flex items-center justify-between">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
            Compare
          </div>
          <div className="text-xs text-strata-dim">two tickers, side by side</div>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            disabled
            title="Add ticker — coming in Phase 4.7"
            className="cursor-not-allowed rounded-md border border-strata-border bg-strata-surface px-3 py-1.5 font-mono text-xs text-strata-muted opacity-60"
          >
            + Add ticker
          </button>
          <button
            type="button"
            onClick={onSwap}
            className="rounded-md border border-strata-border bg-strata-surface px-3 py-1.5 font-mono text-xs text-strata-fg transition hover:border-strata-highlight"
          >
            ⇄ Swap
          </button>
        </div>
      </div>

      <div className="mb-6">
        <CompareHero
          a={heroA}
          b={heroB}
          signalsA={signalsA}
          signalsB={signalsB}
        />
      </div>

      <div className="mb-6 grid grid-cols-1 items-start gap-6 lg:grid-cols-2">
        <CompareMetricRow title="Valuation" cells={valuationCells} />
        <CompareMetricRow title="Quality" cells={qualityCells} />
      </div>

      <div className="mb-6">
        <CompareMarginOverlay a={reportA} b={reportB} />
      </div>

      <div className="mb-6 grid grid-cols-1 items-start gap-6 lg:grid-cols-[3fr_2fr]">
        <CompareGrowthOverlay a={reportA} b={reportB} />
        <CompareRiskDiff a={reportA} b={reportB} />
      </div>

      <CompareFooter />
    </div>
  );
}

export default ComparePage;
