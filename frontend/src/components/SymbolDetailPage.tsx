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
import { ErrorBanner } from "./ErrorBanner";
import { LoadingState } from "./LoadingState";
import { ReportRenderer } from "./ReportRenderer";

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

  return (
    <div className="mx-auto max-w-6xl px-8 py-8">
      {/* Hero placeholder — Phase 4.1 fills this in with the price
          chart + featured stats card. The data-testid lets tests
          and downstream PRs find the slot. */}
      <div
        data-testid="hero-placeholder"
        className="mb-6 flex h-[200px] items-center justify-center rounded-xl border border-dashed border-strata-border bg-strata-surface text-xs uppercase tracking-kicker text-strata-muted"
      >
        Hero · Phase 4.1
      </div>

      {reportQuery.isPending && <LoadingState symbol={upperTicker} />}
      {reportQuery.error && !(reportQuery.error instanceof ApiError && reportQuery.error.status === 401) && (
        <ErrorBanner error={reportQuery.error} />
      )}
      {reportQuery.data && <ReportRenderer report={reportQuery.data} />}
    </div>
  );
}
