/**
 * CompareMarginOverlay — Phase 4.6.A.
 *
 * Operating-margin time series for both tickers on a shared axis.
 * Wraps MultiLine with the compare-page chrome (kicker + framing
 * caption). Returns null when neither ticker has the underlying data
 * so the parent layout can collapse cleanly.
 */
import { fractionPct, fractionPctTick, pointsChange } from "../../lib/chart-format";
import { extractCompareMarginOverlay } from "../../lib/compare-extract";
import type { ResearchReport } from "../../lib/schemas";
import { MultiLine } from "../MultiLine";

interface Props {
  a: ResearchReport;
  b: ResearchReport;
}

export function CompareMarginOverlay({ a, b }: Props) {
  const series = extractCompareMarginOverlay(a, b);
  if (series.length === 0) return null;
  // The title used to say "20Q"; the history is ~5 quarters.
  const quarters = Math.max(0, ...series.map((s) => s.history.length));

  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-3 flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-quality">
          Operating margin by quarter · {quarters}Q
        </div>
      </div>
      <MultiLine
        series={series}
        ariaLabel="Operating margin overlay"
        height={180}
        includeZero
        formatValue={fractionPct}
        formatTick={fractionPctTick}
        formatChange={pointsChange}
      />
    </section>
  );
}
