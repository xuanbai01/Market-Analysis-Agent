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
import { EarningsCard } from "./EarningsCard";
import { ErrorBanner } from "./ErrorBanner";
import { HeroCard } from "./HeroCard";
import { LoadingState } from "./LoadingState";
import { QualityCard } from "./QualityCard";
import { ReportRenderer } from "./ReportRenderer";
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

  // Phase 4.1+ — pluck dedicated-card sections (Earnings, Valuation,
  // Quality, Peers) so the new Strata cards can render them; pass the
  // remaining sections to ReportRenderer via excludeSections so we
  // don't double up. Each card no-ops gracefully when its section is
  // missing (EARNINGS focus, pre-cached data, upstream tool failure).
  const earningsSection = reportQuery.data?.sections.find(
    (s) => s.title === "Earnings",
  );
  const qualitySection = reportQuery.data?.sections.find(
    (s) => s.title === "Quality",
  );

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      {reportQuery.isPending && <LoadingState symbol={upperTicker} />}
      {reportQuery.error && !(reportQuery.error instanceof ApiError && reportQuery.error.status === 401) && (
        <ErrorBanner error={reportQuery.error} />
      )}
      {reportQuery.data && (
        <>
          <HeroCard report={reportQuery.data} />
          {earningsSection && <EarningsCard section={earningsSection} />}
          <ValuationCard report={reportQuery.data} />
          {qualitySection && (
            <QualityCard ticker={upperTicker} section={qualitySection} />
          )}
          <ReportRenderer
            report={reportQuery.data}
            excludeSections={["Earnings", "Valuation", "Quality", "Peers"]}
          />
        </>
      )}
    </div>
  );
}
