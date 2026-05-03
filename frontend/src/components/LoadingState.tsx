/**
 * Loading state shown during research synthesis.
 *
 * Synth on a cache miss takes 30–90 seconds (LLM call + EDGAR fan-out
 * for uncached filings). Phase 4.3.X widened the "~30 seconds" copy
 * after the dogfood pass measured ~85 seconds for a fresh AAPL gen.
 *
 * Above the prose: a ghost skeleton of the dashboard's row layout
 * (Hero + 3 grid rows) so the user has spatial context for what's
 * loading. The skeleton uses ``animate-pulse`` for the canonical
 * "loading" affordance and matches the layout SymbolDetailPage will
 * render once the report arrives.
 */
export function LoadingState({ symbol }: { symbol: string }) {
  return (
    <div className="space-y-6">
      <div className="rounded-md border border-strata-border bg-strata-surface p-6 text-center">
        <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-strata-line border-t-strata-fg" />
        <p className="text-sm font-medium text-strata-hi">
          Generating report for {symbol}…
        </p>
        <p className="mt-2 text-xs text-strata-dim">
          First generation takes 30–90 seconds (LLM synthesis + SEC
          filings, longer on uncached filings). Subsequent reads of
          the same symbol are instant.
        </p>
      </div>

      {/* Ghost skeleton matching SymbolDetailPage's row layout. The
          shapes intentionally mirror the real component widths so the
          user's eye has somewhere to settle while the synth completes. */}
      <div data-testid="dashboard-skeleton" className="space-y-6 opacity-60">
        <SkeletonHero />
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <SkeletonCard className="lg:col-span-2 h-[420px]" />
          <SkeletonCard className="lg:col-span-3 h-[420px]" />
        </div>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-5">
          <SkeletonCard className="lg:col-span-2 h-[420px]" />
          <SkeletonCard className="lg:col-span-3 h-[420px]" />
        </div>
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <SkeletonCard className="h-[280px]" />
          <SkeletonCard className="h-[280px]" />
          <SkeletonCard className="h-[280px]" />
        </div>
      </div>
    </div>
  );
}

function SkeletonHero() {
  return (
    <div className="h-[220px] animate-pulse rounded-xl border border-strata-border bg-strata-surface" />
  );
}

function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-md border border-strata-border bg-strata-surface ${className}`}
    />
  );
}
