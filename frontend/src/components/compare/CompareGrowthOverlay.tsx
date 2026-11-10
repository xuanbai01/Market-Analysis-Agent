/**
 * CompareGrowthOverlay — Phase 4.6.A; redrawn in the 2026-11 chart audit.
 *
 * Revenue and FCF per share for both tickers, each indexed to its first
 * quarter = 100, as two panels with one line per company, and each
 * company's year-over-year change under each panel. It used to be one
 * chart of four lines titled "5Y" (the data is ~5 quarters) in which a
 * company's revenue and FCF lines shared a colour.
 */
import { indexValue } from "../../lib/chart-format";
import { COMPARE_COLOR_A, COMPARE_COLOR_B, extractCompareGrowthPanels } from "../../lib/compare-extract";
import { extractGrowthChanges, type GrowthChange } from "../../lib/growth-extract";
import type { ResearchReport } from "../../lib/schemas";
import { MultiLine, type MultiLineSeries } from "../MultiLine";

interface Props {
  a: ResearchReport;
  b: ResearchReport;
}

function formatChange(c: GrowthChange | null): string {
  if (c === null || !Number.isFinite(c.value)) return "—";
  if (c.kind === "usd") return `${c.value >= 0 ? "+" : "-"}$${Math.abs(c.value).toFixed(2)}`;
  const pct = c.value * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(Math.abs(pct) >= 100 ? 0 : 1)}%`;
}

function quality(report: ResearchReport) {
  return report.sections.find((s) => s.title === "Quality");
}

function Panel({
  title,
  series,
  changes,
}: {
  title: string;
  series: MultiLineSeries[];
  changes: { symbol: string; color: string; change: GrowthChange | null }[];
}) {
  return (
    <div data-testid="compare-growth-panel">
      <div className="mb-1 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">{title}</div>
      {series.length > 0 ? (
        <MultiLine
          series={series}
          height={170}
          baseline={100}
          formatValue={indexValue}
          showLegend={false}
          ariaLabel={`${title}, indexed`}
        />
      ) : (
        <div className="flex h-[170px] items-center justify-center font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
          Not comparable (no positive starting value)
        </div>
      )}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px]">
        {changes.map((c) => (
          <span key={c.symbol} className="inline-flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block h-2 w-2 rounded-sm" style={{ backgroundColor: c.color }} />
            <span className="text-strata-dim">{c.symbol}</span>
            <span className="text-strata-hi">{formatChange(c.change)}</span>
            <span className="text-strata-muted">{c.change?.yearOverYear ? "YoY" : c.change?.basis ?? ""}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export function CompareGrowthOverlay({ a, b }: Props) {
  const panels = extractCompareGrowthPanels(a, b);
  if (panels.revenue.length === 0 && panels.fcf.length === 0) return null;

  const qa = quality(a);
  const qb = quality(b);
  const changesA = qa ? extractGrowthChanges(qa) : null;
  const changesB = qb ? extractGrowthChanges(qb) : null;
  const quarters = Math.max(0, ...[...panels.revenue, ...panels.fcf].map((s) => s.history.length));
  const colorFor = (symbol: string) => (symbol === a.symbol ? COMPARE_COLOR_A : COMPARE_COLOR_B);

  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-growth">
        Per-share growth · {quarters} quarters · first quarter = 100
      </div>
      <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
        <Panel
          title="Revenue / share"
          series={panels.revenue}
          changes={[
            { symbol: a.symbol, color: colorFor(a.symbol), change: changesA?.rev ?? null },
            { symbol: b.symbol, color: colorFor(b.symbol), change: changesB?.rev ?? null },
          ]}
        />
        <Panel
          title="Free cash flow / share"
          series={panels.fcf}
          changes={[
            { symbol: a.symbol, color: colorFor(a.symbol), change: changesA?.fcf ?? null },
            { symbol: b.symbol, color: colorFor(b.symbol), change: changesB?.fcf ?? null },
          ]}
        />
      </div>
    </section>
  );
}
