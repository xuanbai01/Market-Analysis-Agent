/**
 * CompareGrowthOverlay — Phase 4.6.A.
 *
 * 5Y per-share growth for both tickers, rebased to 100. Plots up to
 * 4 series (Revenue + FCF per share, per ticker). Footer shows the
 * end-period multiplier per series so a viewer can read "NVDA Rev 6.2×"
 * at a glance even when the chart is dense.
 */
import {
  COMPARE_COLOR_A,
  COMPARE_COLOR_B,
  extractCompareGrowthOverlay,
} from "../../lib/compare-extract";
import type { ResearchReport } from "../../lib/schemas";
import { MultiLine } from "../MultiLine";

interface Props {
  a: ResearchReport;
  b: ResearchReport;
}

export function CompareGrowthOverlay({ a, b }: Props) {
  const series = extractCompareGrowthOverlay(a, b);
  if (series.length === 0) return null;

  // Multiplier at the end period per series — last rebased value / 100.
  const multipliers = series.map((s) => {
    const last = s.history[s.history.length - 1]?.value ?? 0;
    return { label: s.label, color: s.color, multiplier: last / 100 };
  });

  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-3 flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-growth">
          Per-share growth · 5Y · rebased to 100
        </div>
      </div>
      <MultiLine series={series} ariaLabel="Per-share growth overlay" height={180} />
      <div className="mt-3 flex flex-wrap items-center gap-3 font-mono text-[11px] uppercase tracking-wide">
        {multipliers.map((m) => (
          <span key={m.label} className="flex items-center gap-1.5">
            <span
              aria-hidden
              className="inline-block h-2 w-2 rounded-full"
              style={{ backgroundColor: m.color === COMPARE_COLOR_A || m.color === COMPARE_COLOR_B ? m.color : COMPARE_COLOR_A }}
            />
            <span className="text-strata-dim">{m.label}</span>
            <span className="text-strata-hi">{m.multiplier.toFixed(1)}×</span>
          </span>
        ))}
      </div>
    </section>
  );
}
