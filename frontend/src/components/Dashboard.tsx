/**
 * Authenticated dashboard. Two columns:
 *
 * Left: ReportForm at the top, then the active ResearchReport (or
 * loading state, or error banner).
 *
 * Right: PastReportsList — sidebar of cached reports. Click → re-fetch
 * the full report (cache hit; <1s).
 *
 * State management:
 *
 * - ``activeKey`` is a tuple identifying which report is "in view".
 *   Switching to a past report rewrites this.
 * - ``useMutation`` handles fresh report generation (form submit).
 *   On success it invalidates the past-reports list so the new
 *   report shows up in the sidebar.
 * - ``useQuery(["report", ...activeKey])`` re-fetches when activeKey
 *   changes — i.e. when the user clicks a past report.
 *
 * 401 handling is centralized: any 401 from the API kicks the user
 * back to the login screen via ``onSignOut``.
 */
import { useEffect, useMemo, useState } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  ApiError,
  fetchResearchReport,
  listResearchReports,
} from "../lib/api";
import { clearStoredToken } from "../lib/auth";
import type { Focus, ResearchReportSummary } from "../lib/schemas";
import { ErrorBanner } from "./ErrorBanner";
import { LoadingState } from "./LoadingState";
import { PastReportsList } from "./PastReportsList";
import {
  ReportForm,
  type ReportFormSubmit,
} from "./ReportForm";
import { ReportRenderer } from "./ReportRenderer";

interface Props {
  onSignOut: () => void;
}

interface ActiveReportKey {
  symbol: string;
  focus: Focus;
  refresh?: boolean;
  /** Bumped to force a re-fetch even when symbol+focus unchanged. */
  nonce: number;
}

export function Dashboard({ onSignOut }: Props) {
  const queryClient = useQueryClient();
  const [active, setActive] = useState<ActiveReportKey | null>(null);

  // Past-reports list (sidebar).
  const summariesQuery = useQuery({
    queryKey: ["past-reports"],
    queryFn: () => listResearchReports({ limit: 20 }),
    staleTime: 30_000,
  });

  // Fresh-report generation. Wrapped as a mutation because it has
  // side effects (cache write on the backend, rate-limit token spend).
  const generateMutation = useMutation({
    mutationFn: (submit: ReportFormSubmit) =>
      fetchResearchReport(submit.symbol, {
        focus: submit.focus,
        refresh: submit.refresh,
      }),
    onSuccess: (_data, variables) => {
      // Invalidate so the new row shows up in the sidebar.
      queryClient.invalidateQueries({ queryKey: ["past-reports"] });
      setActive({
        symbol: variables.symbol,
        focus: variables.focus,
        nonce: Date.now(),
      });
    },
  });

  // Past-report click → re-fetch the full report (cache hit).
  const replayQuery = useQuery({
    queryKey: ["report", active?.symbol, active?.focus, active?.nonce],
    queryFn: () =>
      fetchResearchReport(active!.symbol, { focus: active!.focus }),
    enabled: !!active && !generateMutation.isPending,
    staleTime: 60_000,
  });

  // Centralized 401 handler — any path that returns 401 (probe expired,
  // secret rotated, etc) kicks the user out to login.
  useEffect(() => {
    for (const err of [
      summariesQuery.error,
      generateMutation.error,
      replayQuery.error,
    ]) {
      if (err instanceof ApiError && err.status === 401) {
        clearStoredToken();
        onSignOut();
        return;
      }
    }
  }, [
    summariesQuery.error,
    generateMutation.error,
    replayQuery.error,
    onSignOut,
  ]);

  // Decide which "main view" to show. Mutation pending wins (we're
  // actively generating). Then the active report. Then a placeholder.
  const mainView = useMemo(() => {
    if (generateMutation.isPending) {
      return (
        <LoadingState symbol={generateMutation.variables?.symbol ?? ""} />
      );
    }
    if (generateMutation.error) {
      return <ErrorBanner error={generateMutation.error} />;
    }
    if (active && replayQuery.isPending) {
      return <LoadingState symbol={active.symbol} />;
    }
    if (replayQuery.error) {
      return <ErrorBanner error={replayQuery.error} />;
    }
    if (replayQuery.data) {
      return <ReportRenderer report={replayQuery.data} />;
    }
    return (
      <div className="rounded-md border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
        Generate a report or pick one from the sidebar.
      </div>
    );
  }, [generateMutation, active, replayQuery]);

  function handleSelectPast(summary: ResearchReportSummary) {
    setActive({
      symbol: summary.symbol,
      focus: summary.focus as Focus,
      nonce: Date.now(),
    });
  }

  function handleSignOut() {
    clearStoredToken();
    onSignOut();
  }

  const selectedKey = active
    ? {
        symbol: active.symbol,
        focus: active.focus,
        // Past-reports rows match by report_date; we don't carry that
        // through ``ActiveReportKey``, so the sidebar highlight only
        // tracks symbol + focus. Good enough for the dashboard.
        report_date: "",
      }
    : undefined;

  return (
    <div className="min-h-full bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <h1 className="text-lg font-semibold text-slate-900">
            Market Analysis Agent
          </h1>
          <button
            type="button"
            onClick={handleSignOut}
            className="text-sm text-slate-500 hover:text-slate-900"
          >
            Sign out
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-6 py-6">
        <div className="grid gap-6 md:grid-cols-[1fr_280px]">
          <div className="space-y-4">
            <ReportForm
              onSubmit={(s) => generateMutation.mutate(s)}
              isPending={generateMutation.isPending}
              initialSymbol={active?.symbol ?? ""}
            />
            {mainView}
          </div>

          <PastReportsList
            summaries={summariesQuery.data ?? []}
            isLoading={summariesQuery.isPending}
            error={summariesQuery.error}
            onSelect={handleSelectPast}
            selected={selectedKey}
          />
        </div>
      </main>
    </div>
  );
}
