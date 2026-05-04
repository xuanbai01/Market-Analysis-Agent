/**
 * SymbolDetailPage — /symbol/:ticker. The dashboard.
 *
 * Phase 4.0 scope:
 *   - reads :ticker from URL, uppercases before backend call
 *   - fetches the report via the existing TanStack Query path
 *     (POST /v1/research/:ticker, same-day cache hit when available)
 *   - renders a hero placeholder reserving 4.1's space
 *   - renders the existing ReportRenderer below the hero
 *
 * Phase 4.1 fills the hero. Phase 4.2+ replace each ReportRenderer
 * card with Strata variants. SymbolDetailPage stays the host across
 * all of Phase 4.
 */
import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError, fetchResearchReport } from "../lib/api";
import { clearStoredToken } from "../lib/auth";
import { ROUTES } from "../lib/routes";
import { CashAndCapitalCard } from "./CashAndCapitalCard";
import { ContextBand } from "./ContextBand";
import { EarningsCard } from "./EarningsCard";
import { ErrorBanner } from "./ErrorBanner";
import { HeaderPills } from "./HeaderPills";
import { HeroCard } from "./HeroCard";
import { LoadingState } from "./LoadingState";
import { MacroPanel } from "./MacroPanel";
import { PerShareGrowthCard } from "./PerShareGrowthCard";
import { QualityCard } from "./QualityCard";
import { ReportRenderer } from "./ReportRenderer";
import { RiskDiffCard } from "./RiskDiffCard";
import { ValuationCard } from "./ValuationCard";

export function SymbolDetailPage() {
  const { ticker } = useParams<{ ticker: string }>();
  const navigate = useNavigate();
  const upperTicker = (ticker ?? "").toUpperCase();

  const reportQuery = useQuery({
    queryKey: ["report", upperTicker, "full"],
    queryFn: () => fetchResearchReport(upperTicker, { focus: "full" }),
    enabled: upperTicker.length > 0,
    staleTime: 60_000,
  });

  // Centralized 401 handling — clear token + bounce to login.
  useEffect(() => {
    if (
      reportQuery.error instanceof ApiError &&
      reportQuery.error.status === 401
    ) {
      clearStoredToken();
      navigate(ROUTES.login, { replace: true });
    }
  }, [reportQuery.error, navigate]);

  // Phase 4.1+ — pluck dedicated-card sections so the new Strata cards
  // can render them; pass the remaining sections to ReportRenderer via
  // excludeSections so we don't double up. Each card no-ops gracefully
  // when its section is missing (EARNINGS focus, pre-cached data,
  // upstream tool failure).
  //
  // After 4.3.A: Earnings, Valuation, Quality, Peers, Risk Factors,
  // Macro all have dedicated cards. Capital Allocation stays in
  // ReportRenderer for its 6 non-history claims (dividend_yield,
  // buyback_yield, sbc_pct_revenue, short_ratio, shares_short,
  // market_cap) until 4.4 absorbs them into the context band.
  const sections = reportQuery.data?.sections ?? [];
  const earningsSection = sections.find((s) => s.title === "Earnings");
  const qualitySection = sections.find((s) => s.title === "Quality");
  const capAllocSection = sections.find((s) => s.title === "Capital Allocation");
  const riskSection = sections.find((s) => s.title === "Risk Factors");
  const macroSection = sections.find((s) => s.title === "Macro");
  // Phase 4.4.A — Business + News drive the ContextBand between the
  // hero and the row-2 grid.
  const businessSection = sections.find((s) => s.title === "Business");
  const newsSection = sections.find((s) => s.title === "News");

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      {reportQuery.isPending && <LoadingState symbol={upperTicker} />}
      {reportQuery.error && !(reportQuery.error instanceof ApiError && reportQuery.error.status === 401) && (
        <ErrorBanner error={reportQuery.error} />
      )}
      {reportQuery.data && (
        <>
          {/* Phase 4.5.A — diagnostic pills above the hero. Renders
              null on healthy reports so the page header stays clean
              for NVDA / AAPL / etc.; surfaces "● UNPROFITABLE · TTM"
              + "⚠ LIQUIDITY WATCH" + ... for distressed names. */}
          <div className="mb-3 flex justify-end">
            <HeaderPills signals={reportQuery.data.layout_signals} />
          </div>

          <HeroCard report={reportQuery.data} />

          {/* Phase 4.4.A — ContextBand renders Business (left) +
              News (right) between the hero and the row-2 grid.
              Returns null when both sections are absent so older
              cached reports without these fields stay clean. */}
          <ContextBand
            ticker={upperTicker}
            businessSection={businessSection}
            newsSection={newsSection}
          />

          {/* Row 2 — Quality | Earnings.
              Mirrors `direction-strata.jsx` row-2: dense Quality
              card (rings + multi-line) on the left at ~40% width;
              the wider Earnings card with its 20-bar EPS chart on
              the right at ~60%. Stacks to single column under lg. */}
          <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-5">
            {qualitySection && (
              <div className="lg:col-span-2">
                <QualityCard ticker={upperTicker} section={qualitySection} />
              </div>
            )}
            {earningsSection && (
              <div className="lg:col-span-3">
                <EarningsCard section={earningsSection} />
              </div>
            )}
          </div>

          {/* Row 3 — Valuation | Per-share growth.
              Same 40/60 rhythm: ValuationCard (4-cell matrix +
              PeerScatterV2) on the left, the wide PerShareGrowth
              MultiLine on the right.

              Phase 4.4.B — PerShareGrowthCard reads from the Quality
              section (which is QualityCard's primary surface). To
              avoid the LLM's single Quality.card_narrative rendering
              twice on the page (once in QualityCard, once in
              PerShareGrowthCard), suppress the strip on this card by
              passing a section view with card_narrative cleared.
              QualityCard is the canonical home for that prose. When
              4.5+ adds a dedicated growth section, PerShareGrowthCard
              gets its own narrative independently.
          */}
          <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-5">
            <div className="lg:col-span-2">
              <ValuationCard report={reportQuery.data} />
            </div>
            {qualitySection && (
              <div className="lg:col-span-3">
                <PerShareGrowthCard
                  ticker={upperTicker}
                  section={{ ...qualitySection, card_narrative: null }}
                />
              </div>
            )}
          </div>

          {/* Row 4 — Cash & capital | Risk diff | Macro.
              3-column on desktop, stacks on narrower screens. */}
          <div className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-3">
            <CashAndCapitalCard
              capAllocSection={capAllocSection}
              qualitySection={qualitySection}
            />
            {riskSection && <RiskDiffCard section={riskSection} />}
            {macroSection && <MacroPanel section={macroSection} />}
          </div>

          <ReportRenderer
            report={reportQuery.data}
            excludeSections={[
              // Phase 4.4.A — Business + News render in the
              // ContextBand above; exclude them from the trailing
              // ReportRenderer so they don't appear twice.
              "Business",
              "News",
              "Earnings",
              "Valuation",
              "Quality",
              "Peers",
              "Risk Factors",
              "Macro",
            ]}
          />
        </>
      )}
    </div>
  );
}
