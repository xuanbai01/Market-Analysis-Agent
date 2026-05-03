/**
 * Loading state shown during research synthesis.
 *
 * Synth on a cache miss takes ~30s (LLM call + EDGAR fan-out). The
 * primary copy sets that expectation explicitly; without it, users
 * assume the page is broken at the 5s mark. The "subsequent reads
 * are <1s" line softens the wait — it's a one-time cost.
 */
export function LoadingState({ symbol }: { symbol: string }) {
  return (
    <div className="rounded-md border border-strata-border bg-strata-surface p-6 text-center">
      <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-strata-line border-t-strata-fg" />
      <p className="text-sm font-medium text-strata-hi">
        Generating report for {symbol}…
      </p>
      <p className="mt-2 text-xs text-strata-dim">
        First generation takes ~30 seconds (LLM synthesis + SEC filings).
        Subsequent reads of the same symbol are instant.
      </p>
    </div>
  );
}
