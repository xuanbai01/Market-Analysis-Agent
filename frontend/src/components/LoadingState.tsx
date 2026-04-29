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
    <div className="rounded-md border border-slate-200 bg-white p-6 text-center shadow-sm">
      <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-slate-200 border-t-slate-700" />
      <p className="text-sm font-medium text-slate-900">
        Generating report for {symbol}…
      </p>
      <p className="mt-2 text-xs text-slate-500">
        First generation takes ~30 seconds (LLM synthesis + SEC filings).
        Subsequent reads of the same symbol are instant.
      </p>
    </div>
  );
}
