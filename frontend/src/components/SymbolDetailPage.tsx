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
 *
 * Phase 4.5.C layout polish:
 *   - max-w-screen-2xl container (was max-w-6xl) so dashboards
 *     breathe at 1920px+ resolutions
 *   - items-start on every multi-column grid so cards align top
 *     and accept honest height gaps as breathing room
 *   - row 4 (Cash+Risk+Macro) auto-collapses to N columns when
 *     fewer cards have data — placeholders no longer waste slots
 *   - ContextBand (Business + News) moved to bottom (after row 4)
 *     instead of above row 2.
 */
import { useEffect, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError, fetchResearchReport } from "../lib/api";
import { clearStoredToken } from "../lib/auth";
import { ROUTES } from "../lib/routes";
import type { ResearchReport, Section } from "../lib/schemas";
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
  const sections = reportQuery.data?.sections ?? [];
  const earningsSection = sections.find((s) => s.title === "Earnings");
  const qualitySection = sections.find((s) => s.title === "Quality");
  const capAllocSection = sections.find((s) => s.title === "Capital Allocation");
  const riskSection = sections.find((s) => s.title === "Risk Factors");
  const macroSection = sections.find((s) => s.title === "Macro");
  const businessSection = sections.find((s) => s.title === "Business");
  const newsSection = sections.find((s) => s.title === "News");

  return (
    <div
      data-testid="dashboard-container"
      className="mx-auto w-full max-w-screen-2xl px-6 py-8 lg:px-8 xl:px-10"
    >
      {reportQuery.isPending && <LoadingState symbol={upperTicker} />}
      {reportQuery.error && !(reportQuery.error instanceof ApiError && reportQuery.error.status === 401) && (
        <ErrorBanner error={reportQuery.error} />
      )}
      {reportQuery.data && (
        <>
          {/* Phase 4.5.A — diagnostic pills above the hero. */}
          <div className="mb-3 flex justify-end">
            <HeaderPills signals={reportQuery.data.layout_signals} />
          </div>

          <HeroCard report={reportQuery.data} />

          {/* Row 2 — Quality | Earnings.
              40/60 rhythm; ``items-start`` so cards align top with
              honest height gaps rather than stretch-fill. */}
          <div className="mb-6 grid grid-cols-1 items-start gap-6 lg:grid-cols-5">
            {qualitySection && (
              <div className="lg:col-span-2">
                <QualityCard ticker={upperTicker} section={qualitySection} />
              </div>
            )}
            {earningsSection && (
              <div className="lg:col-span-3">
                <EarningsCard
                  section={earningsSection}
                  distressed={{
                    beat_rate_below_30pct:
                      reportQuery.data.layout_signals.beat_rate_below_30pct,
                  }}
                />
              </div>
            )}
          </div>

          {/*
            Phase 4.5.B — adaptive row ordering.
            Default (healthy):
              Row 3 = Valuation + PerShareGrowth (40/60)
              Row 4 = Cash + Risk + Macro (1, 2, or 3 cols)
            Distressed (is_unprofitable_ttm OR runway < 6):
              Row 3 = Cash + Risk + Macro  (lifted up — survival first)
              Row 4 = Valuation + PerShareGrowth (demoted)

            Phase 4.5.C — row 4's Cash+Risk+Macro grid collapses to
            data-card-count cols (1, 2, or 3) so missing
            RiskDiffCard / MacroPanel don't leave blank slots.
          */}
          <DashboardRows
            ticker={upperTicker}
            report={reportQuery.data}
            qualitySection={qualitySection}
            capAllocSection={capAllocSection}
            riskSection={riskSection}
            macroSection={macroSection}
          />

          {/* Phase 4.5.C — ContextBand moved from above row 2 to
              below row 4. Business description + recent news read
              less urgent than the numeric rows; keeping them at the
              bottom avoids burying the hero stat trio. Returns null
              when both sections are absent so older cached reports
              without these fields stay clean. */}
          <ContextBand
            ticker={upperTicker}
            businessSection={businessSection}
            newsSection={newsSection}
          />

          <ReportRenderer
            report={reportQuery.data}
            excludeSections={[
              // Business + News render in the ContextBand above; exclude
              // them from the trailing ReportRenderer so they don't
              // appear twice.
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

interface DashboardRowsProps {
  ticker: string;
  report: ResearchReport;
  qualitySection: Section | undefined;
  capAllocSection: Section | undefined;
  riskSection: Section | undefined;
  macroSection: Section | undefined;
}

/** Phase 4.5.B + 4.5.C — rows 3 + 4 with adaptive ordering and
 *  auto-collapsing column count. Pulled out of SymbolDetailPage to
 *  keep the inner JSX readable. */
function DashboardRows(props: DashboardRowsProps) {
  const {
    ticker,
    report,
    qualitySection,
    capAllocSection,
    riskSection,
    macroSection,
  } = props;

  const signals = report.layout_signals;
  const isDistressed =
    signals.is_unprofitable_ttm ||
    (signals.cash_runway_quarters !== null &&
      signals.cash_runway_quarters < 6);

  // Decide which Cash/Risk/Macro cards have data ahead of render so
  // the grid's column count adapts. RiskDiffCard + MacroPanel return
  // null on unavailable data (Phase 4.5.C); CashAndCapitalCard always
  // renders (it has its own internal fallback for missing data).
  const cashRiskMacroCards: ReactNode[] = [
    <CashAndCapitalCard
      key="cash"
      capAllocSection={capAllocSection}
      qualitySection={qualitySection}
      runwayQuarters={signals.cash_runway_quarters}
    />,
  ];
  if (riskSection && riskSection.claims.length > 0) {
    cashRiskMacroCards.push(<RiskDiffCard key="risk" section={riskSection} />);
  }
  if (macroSection && macroSection.claims.length > 0) {
    cashRiskMacroCards.push(<MacroPanel key="macro" section={macroSection} />);
  }
  const cashRiskMacroCount = cashRiskMacroCards.length;
  // Tailwind needs literal class names; switch on count.
  const crmGridCols =
    cashRiskMacroCount === 3
      ? "lg:grid-cols-3"
      : cashRiskMacroCount === 2
        ? "lg:grid-cols-2"
        : "lg:grid-cols-1";

  const valuationGrowthRow = (
    <div className="mb-6 grid grid-cols-1 items-start gap-6 lg:grid-cols-5">
      <div className="lg:col-span-2">
        <ValuationCard report={report} />
      </div>
      {qualitySection && (
        <div className="lg:col-span-3">
          <PerShareGrowthCard
            ticker={ticker}
            section={{ ...qualitySection, card_narrative: null }}
          />
        </div>
      )}
    </div>
  );

  const cashRiskMacroRow = (
    <div
      className={`mb-6 grid grid-cols-1 items-start gap-6 ${crmGridCols}`}
    >
      {cashRiskMacroCards}
    </div>
  );

  const valuationGrowthCount = qualitySection ? 2 : 1;

  return (
    <>
      <div
        data-row="dashboard-row-3"
        data-row-content={isDistressed ? "cash-risk-macro" : "valuation-growth"}
        data-card-count={String(
          isDistressed ? cashRiskMacroCount : valuationGrowthCount,
        )}
      >
        {isDistressed ? cashRiskMacroRow : valuationGrowthRow}
      </div>
      <div
        data-row="dashboard-row-4"
        data-row-content={isDistressed ? "valuation-growth" : "cash-risk-macro"}
        data-card-count={String(
          isDistressed ? valuationGrowthCount : cashRiskMacroCount,
        )}
      >
        {isDistressed ? valuationGrowthRow : cashRiskMacroRow}
      </div>
    </>
  );
}
