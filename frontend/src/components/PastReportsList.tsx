/**
 * Sidebar list of past reports.
 *
 * Driven by ``GET /v1/research?limit=20``. Click a row → re-fetch the
 * full report via the existing endpoint (which hits the same-day
 * cache, so this is sub-second).
 *
 * Empty state, error state, and loading state all rendered inline so
 * the parent doesn't have to know about them.
 */
import type { ResearchReportSummary } from "../lib/schemas";
import { ConfidenceBadge } from "./ConfidenceBadge";

interface Props {
  summaries: ResearchReportSummary[];
  isLoading: boolean;
  error: unknown;
  onSelect: (summary: ResearchReportSummary) => void;
  /** When set, that row gets a "selected" highlight. */
  selected?: { symbol: string; focus: string; report_date: string };
}

export function PastReportsList({
  summaries,
  isLoading,
  error,
  onSelect,
  selected,
}: Props) {
  return (
    <aside className="space-y-2">
      <h3 className="px-1 text-xs font-medium uppercase tracking-wide text-slate-500">
        Past reports
      </h3>

      {isLoading && (
        <p className="px-2 text-xs text-slate-500">Loading…</p>
      )}

      {error !== null && error !== undefined && !isLoading && (
        <p className="px-2 text-xs text-red-600">Could not load past reports.</p>
      )}

      {!isLoading && summaries.length === 0 && error == null && (
        <p className="px-2 text-xs text-slate-500">
          Nothing yet. Generate one above.
        </p>
      )}

      <ul className="space-y-1">
        {summaries.map((summary) => {
          const isSelected =
            selected !== undefined &&
            selected.symbol === summary.symbol &&
            selected.focus === summary.focus &&
            selected.report_date === summary.report_date;

          return (
            <li key={`${summary.symbol}-${summary.focus}-${summary.report_date}`}>
              <button
                type="button"
                onClick={() => onSelect(summary)}
                className={`group flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-sm transition ${
                  isSelected
                    ? "bg-slate-200 text-slate-900"
                    : "hover:bg-slate-100"
                }`}
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-slate-900">
                    {summary.symbol}
                    <span className="ml-1 text-xs font-normal text-slate-500">
                      {summary.focus}
                    </span>
                  </p>
                  <p className="text-xs text-slate-500">
                    {summary.report_date}
                  </p>
                </div>
                <ConfidenceBadge
                  confidence={summary.overall_confidence}
                  size="sm"
                />
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
