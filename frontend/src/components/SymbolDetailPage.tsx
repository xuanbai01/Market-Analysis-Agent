/**
 * SymbolDetailPage — /symbol/:ticker. The dashboard.
 *
 * 2026-11 layout pass. Rows of uneven cards left holes (Quality ran
 * 1,475 px beside a 636 px Earnings card) and a third column reserved
 * for a Macro card that rendered nothing. The layout now:
 *
 *   header      freshness · confidence · pills · watchlist
 *   SectionNav  sticky links to every section on the page
 *   Overview    HeroCard
 *   Analyst     AnalystViewCard
 *   Quality     full width — the card lays out two columns at lg
 *   Earnings    full width — idem
 *   ┌ Valuation full width — idem          ┐ swapped with the row
 *   └ Growth    PerShareGrowthCard          ┘ below for distressed names
 *   small row   Cash & capital · Capital returns · Risk · Macro —
 *               only the cards with data, one column each, equal height
 *   context     Business · News — equal height
 *
 * Cards are flex columns filling their grid cell (``h-full``) and rows
 * stretch, so cards side by side share a height; a card's narrative
 * strip sits at its bottom. Whether a card is in a row is decided by
 * the same check the card uses to render, so no row reserves a slot for
 * an empty card. Each section's wrapper carries ``data-section-anchor``
 * (+ a label for SectionNav) and ``scroll-mt-16`` so jumps land below
 * the sticky bar.
 */
import { useEffect, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError, fetchResearchReport } from "../lib/api";
import { clearStoredToken } from "../lib/auth";
import { hasCapitalReturns } from "../lib/capital-returns-extract";
import { extractMacroPanels } from "../lib/macro-extract";
import { pushRecent } from "../lib/recent";
import { extractRiskDiffBars, extractRiskDiffSummary } from "../lib/risk-extract";
import { ROUTES } from "../lib/routes";
import type { ResearchReport, Section } from "../lib/schemas";
import { AnalystViewCard } from "./AnalystViewCard";
import { CapitalReturnsCard } from "./CapitalReturnsCard";
import { CashAndCapitalCard } from "./CashAndCapitalCard";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { ContextBand } from "./ContextBand";
import { EarningsCard } from "./EarningsCard";
import { ErrorBanner } from "./ErrorBanner";
import { ErrorBoundary } from "./ErrorBoundary";
import { HeaderPills } from "./HeaderPills";
import { HeroCard } from "./HeroCard";
import { LoadingState } from "./LoadingState";
import { MacroPanel } from "./MacroPanel";
import { PerShareGrowthCard } from "./PerShareGrowthCard";
import { QualityCard } from "./QualityCard";
import { ReportRenderer } from "./ReportRenderer";
import { ReportFreshness } from "./ReportFreshness";
import { RiskDiffCard } from "./RiskDiffCard";
import { SectionNav } from "./SectionNav";
import { ValuationCard } from "./ValuationCard";
import { WatchlistButton } from "./WatchlistButton";

/** Sections drawn by dedicated cards; anything else falls to ReportRenderer. */
const CARD_SECTIONS = [
  "Business",
  "News",
  "Earnings",
  "Valuation",
  "Quality",
  "Peers",
  "Risk Factors",
  "Macro",
  "Capital Allocation",
];

/** Peers listed in the Peers section ("PG, PEP, CL"). */
function peersOf(section: Section | undefined): string[] {
  const claim = section?.claims.find((c) => c.description === "Peers selected for comparison");
  return typeof claim?.value === "string"
    ? claim.value.split(",").map((p) => p.trim()).filter(Boolean)
    : [];
}

interface AnchorProps {
  anchor: string;
  label: string;
  className?: string;
  children: ReactNode;
}

/** A section's wrapper: the scroll target for SectionNav and evidence chips. */
function Anchor({ anchor, label, className = "", children }: AnchorProps) {
  return (
    <div data-section-anchor={anchor} data-section-label={label} className={`scroll-mt-16 ${className}`}>
      {children}
    </div>
  );
}

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

  // Phase 4.7 — push the ticker onto the MRU recent list once the
  // report has actually loaded (typos / 404 tickers stay out).
  useEffect(() => {
    if (reportQuery.data && upperTicker) {
      pushRecent(upperTicker);
    }
  }, [reportQuery.data, upperTicker]);

  const report = reportQuery.data;
  const sections = report?.sections ?? [];
  const find = (title: string) => sections.find((s) => s.title === title);
  const earningsSection = find("Earnings");
  const qualitySection = find("Quality");
  const businessSection = find("Business");
  const newsSection = find("News");
  const otherSections = sections.filter((s) => !CARD_SECTIONS.includes(s.title));
  const reportKey = `${upperTicker}:${report?.generated_at ?? ""}`;

  return (
    <div
      data-testid="dashboard-container"
      className="mx-auto w-full max-w-screen-2xl px-6 py-8 lg:px-8 xl:px-10"
    >
      {reportQuery.isPending && <LoadingState symbol={upperTicker} />}
      {reportQuery.error && !(reportQuery.error instanceof ApiError && reportQuery.error.status === 401) && (
        <ErrorBanner error={reportQuery.error} />
      )}
      {report && (
        <>
          {/* Report age + Regenerate, overall confidence, diagnostic
              pills, watchlist star. */}
          <div className="mb-3 flex items-center justify-end gap-2">
            <ReportFreshness ticker={upperTicker} generatedAt={report.generated_at} />
            <span className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
              Confidence
              <ConfidenceBadge confidence={report.overall_confidence} size="sm" />
            </span>
            <HeaderPills signals={report.layout_signals} />
            <WatchlistButton ticker={upperTicker} />
          </div>

          <SectionNav refreshKey={reportKey} />

          {/* Every card sits in its own ErrorBoundary: one that meets
              data it can't draw shows a notice in its place instead of
              blanking the page; ``reportKey`` retries them. */}
          <Anchor anchor="Overview" label="Overview">
            <ErrorBoundary label="Overview" resetKey={reportKey}>
              <HeroCard report={report} />
            </ErrorBoundary>
          </Anchor>

          <Anchor anchor="Analyst view" label="Analyst view">
            <ErrorBoundary label="Analyst view" resetKey={reportKey}>
              <AnalystViewCard report={report} />
            </ErrorBoundary>
          </Anchor>

          {qualitySection && (
            <Anchor anchor="Quality" label="Quality" className="mb-6">
              <ErrorBoundary label="Quality" resetKey={reportKey}>
                <QualityCard ticker={upperTicker} section={qualitySection} />
              </ErrorBoundary>
            </Anchor>
          )}

          {earningsSection && (
            <Anchor anchor="Earnings" label="Earnings" className="mb-6">
              <ErrorBoundary label="Earnings" resetKey={reportKey}>
                <EarningsCard
                  section={earningsSection}
                  distressed={{ beat_rate_below_30pct: report.layout_signals.beat_rate_below_30pct }}
                />
              </ErrorBoundary>
            </Anchor>
          )}

          <DashboardRows reportKey={reportKey} ticker={upperTicker} report={report} />

          {(businessSection || newsSection) && (
            <Anchor anchor="News" label="Business & news">
              <ErrorBoundary label="Business & news" resetKey={reportKey}>
                <ContextBand
                  ticker={upperTicker}
                  businessSection={businessSection}
                  newsSection={newsSection}
                  sector={report.sector}
                  peers={peersOf(find("Peers"))}
                />
              </ErrorBoundary>
            </Anchor>
          )}

          {otherSections.length > 0 && (
            <ErrorBoundary label="Other sections" resetKey={reportKey}>
              <ReportRenderer report={report} excludeSections={CARD_SECTIONS} />
            </ErrorBoundary>
          )}
        </>
      )}
    </div>
  );
}

interface DashboardRowsProps {
  reportKey: string;
  ticker: string;
  report: ResearchReport;
}

// Literal class names (Tailwind) for 1–4 equal-height cards in a row;
// four go 2×2 until the screen is wide enough for one line.
const SMALL_ROW_COLS = ["", "lg:grid-cols-1", "lg:grid-cols-2", "lg:grid-cols-3", "lg:grid-cols-2 2xl:grid-cols-4"];

/** Valuation + growth, and the small-cards row — swapped for
 *  distressed names (Phase 4.5.B: the survival story comes first). */
function DashboardRows({ reportKey, ticker, report }: DashboardRowsProps) {
  const find = (title: string) => report.sections.find((s) => s.title === title);
  const qualitySection = find("Quality");
  const capAllocSection = find("Capital Allocation");
  const riskSection = find("Risk Factors");
  const macroSection = find("Macro");
  const signals = report.layout_signals;
  const isDistressed =
    signals.is_unprofitable_ttm ||
    (signals.cash_runway_quarters !== null && signals.cash_runway_quarters < 6);

  // Each card joins the row only when it will draw something — the same
  // checks the cards use to return null.
  const smallCards: ReactNode[] = [
    <Anchor key="cash" anchor="Cash" label="Cash" className="h-full">
      <ErrorBoundary label="Cash & capital" resetKey={reportKey}>
        <CashAndCapitalCard
          capAllocSection={capAllocSection}
          qualitySection={qualitySection}
          runwayQuarters={signals.cash_runway_quarters}
        />
      </ErrorBoundary>
    </Anchor>,
  ];
  if (capAllocSection && hasCapitalReturns(capAllocSection)) {
    smallCards.push(
      <Anchor key="returns" anchor="Capital Allocation" label="Capital returns" className="h-full">
        <ErrorBoundary label="Capital returns" resetKey={reportKey}>
          <CapitalReturnsCard ticker={ticker} section={capAllocSection} />
        </ErrorBoundary>
      </Anchor>,
    );
  }
  if (riskSection && extractRiskDiffBars(riskSection) && extractRiskDiffSummary(riskSection)) {
    smallCards.push(
      <Anchor key="risk" anchor="Risk Factors" label="Risk" className="h-full">
        <ErrorBoundary label="Risk factors" resetKey={reportKey}>
          <RiskDiffCard section={riskSection} />
        </ErrorBoundary>
      </Anchor>,
    );
  }
  if (macroSection && extractMacroPanels(macroSection).length > 0) {
    smallCards.push(
      <Anchor key="macro" anchor="Macro" label="Macro" className="h-full">
        <ErrorBoundary label="Macro" resetKey={reportKey}>
          <MacroPanel section={macroSection} />
        </ErrorBoundary>
      </Anchor>,
    );
  }

  const valuationGrowth = (
    <>
      <Anchor anchor="Valuation" label="Valuation" className="mb-6">
        <ErrorBoundary label="Valuation" resetKey={reportKey}>
          <ValuationCard report={report} />
        </ErrorBoundary>
      </Anchor>
      {qualitySection && (
        <Anchor anchor="Growth" label="Growth" className="mb-6">
          <ErrorBoundary label="Per-share growth" resetKey={reportKey}>
            <PerShareGrowthCard ticker={ticker} section={{ ...qualitySection, card_narrative: null }} />
          </ErrorBoundary>
        </Anchor>
      )}
    </>
  );
  const smallRow = (
    <div className={`mb-6 grid grid-cols-1 gap-6 ${SMALL_ROW_COLS[smallCards.length]}`}>{smallCards}</div>
  );
  const valuationGrowthCount = qualitySection ? 2 : 1;

  return (
    <>
      <div
        data-row="dashboard-row-3"
        data-row-content={isDistressed ? "cash-risk-macro" : "valuation-growth"}
        data-card-count={String(isDistressed ? smallCards.length : valuationGrowthCount)}
      >
        {isDistressed ? smallRow : valuationGrowth}
      </div>
      <div
        data-row="dashboard-row-4"
        data-row-content={isDistressed ? "valuation-growth" : "cash-risk-macro"}
        data-card-count={String(isDistressed ? valuationGrowthCount : smallCards.length)}
      >
        {isDistressed ? valuationGrowth : smallRow}
      </div>
    </>
  );
}

// Phase 4.7 — default export so App.tsx can lazy-load this whole page.
export default SymbolDetailPage;
