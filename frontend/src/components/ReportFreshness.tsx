/**
 * ReportFreshness — "Generated 2 days ago · Regenerate" above the hero.
 *
 * Reports are cached for up to 7 days, so a page can show prose written
 * before a fix shipped (the AAPL card still read "ROE of 1.42" after the
 * units fix). This says how old the report is and lets the user ask for
 * a new one: ``refresh=true`` re-runs the tools and the LLM (30–90 s,
 * counts against the rate limit). The current report stays on screen
 * until the new one replaces it.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ApiError, fetchResearchReport } from "../lib/api";
import { formatAge, formatTimestamp } from "../lib/format";

interface Props {
  ticker: string;
  generatedAt: string;
  /** Show the report's age only: the public demo can't rebuild one. */
  readOnly?: boolean;
}

export function ReportFreshness({ ticker, generatedAt, readOnly = false }: Props) {
  const queryClient = useQueryClient();
  const regenerate = useMutation({
    mutationFn: () => fetchResearchReport(ticker, { focus: "full", refresh: true }),
    onSuccess: (report) => {
      queryClient.setQueryData(["report", ticker, "full"], report);
      void queryClient.invalidateQueries({ queryKey: ["past-reports"] });
    },
  });

  return (
    <div data-testid="report-freshness" className="mr-auto flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] text-strata-muted">
      <span title={formatTimestamp(generatedAt)}>Generated {formatAge(generatedAt)}</span>
      {!readOnly && (
        <>
      <span aria-hidden="true">·</span>
      <button
        type="button"
        onClick={() => regenerate.mutate()}
        disabled={regenerate.isPending}
        className="rounded text-strata-highlight hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight disabled:cursor-wait disabled:text-strata-dim disabled:no-underline"
      >
        {regenerate.isPending ? "Regenerating… (30–90 s)" : "Regenerate"}
      </button>
        </>
      )}
      {regenerate.isError && (
        <span role="alert" className="text-strata-neg">
          Couldn&apos;t regenerate: {errorText(regenerate.error)}
        </span>
      )}
    </div>
  );
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 429) {
      const minutes = error.retryAfterSeconds ? Math.ceil(error.retryAfterSeconds / 60) : null;
      return minutes ? `rate limit reached, try again in ${minutes} min.` : "rate limit reached, try again later.";
    }
    return error.title;
  }
  return error instanceof Error ? error.message : "unknown error.";
}
