/**
 * CompareMarginOverlay — Phase 4.6.A.
 *
 * Operating-margin time series for both tickers on a shared axis.
 * Wraps MultiLine with the compare-page chrome (kicker + framing
 * caption). Returns null when neither ticker has the underlying data
 * so the parent layout can collapse cleanly.
 */
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

  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-3 flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-quality">
          Operating margin · 20Q · both tickers
        </div>
      </div>
      <MultiLine series={series} ariaLabel="Operating margin overlay" height={180} />
    </section>
  );
}
