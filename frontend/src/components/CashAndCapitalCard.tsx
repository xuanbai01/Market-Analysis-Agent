/**
 * CashAndCapitalCard — Phase 4.3.A; redrawn 2026-11.
 *
 * Cross-section card: CapEx + SBC per share (Capital Allocation) and
 * Cash + Debt per share (Quality), one tile each — latest value, change
 * since the first quarter, and a sparkline with marked ends — then the
 * Net cash / share highlight (cash − debt at the latest snapshot) and,
 * for cash-burning names, the runway tile.
 *
 * Until 2026-11 the four series were two 80 px line charts with no scale
 * (tasks/dogfood-2026-11.md #9): CapEx $0.11 vs SBC $0.08, or debt
 * tripling, read as flat lines. These are "current value + trend" data,
 * so stat tiles carry them better than charts.
 *
 * Degrades gracefully: a metric without history gets no tile; net cash
 * falls back to an em-dash when either snapshot is missing.
 */
import { usdPerShare } from "../lib/chart-format";
import { formatClaimValue } from "../lib/format";
import {
  extractCapexSbcSeries,
  extractCashDebtSeries,
  extractNetCashPerShare,
} from "../lib/cash-capital-extract";
import type { Section } from "../lib/schemas";
import type { MultiLineSeries } from "./MultiLine";
import { useMeasuredSize } from "../lib/use-measured-width";
import { Sparkline } from "./Sparkline";

interface Props {
  capAllocSection: Section | undefined;
  qualitySection: Section | undefined;
  /** Phase 4.5.B — read from ``layout_signals.cash_runway_quarters``.
   *  When provided (number, including 0.0), the card grows a "Runway"
   *  stat tile alongside the Net cash highlight. ``null`` / undefined
   *  hides the tile (FCF-positive companies, cache-pre-4.5 reports). */
  runwayQuarters?: number | null;
}

const RUNWAY_RAISE_THRESHOLD = 6;

function changeSinceFirst(first: number, last: number): string {
  if (first > 0) {
    const pct = (last / first - 1) * 100;
    return `${pct >= 0 ? "+" : ""}${pct.toFixed(0)}%`;
  }
  const diff = last - first;
  return `${diff >= 0 ? "+" : "-"}${usdPerShare(Math.abs(diff))}`;
}

const SPARK_MIN_H = 26;
// Capped: the sparkline autoscales to its own min–max, so a tall one
// turns a few cents into a cliff.
const SPARK_MAX_H = 48;

function MetricTile({ series }: { series: MultiLineSeries }) {
  // The tiles stretch with the row; the sparkline takes the spare
  // height instead of sitting under a blank band (2026-11 chart audit).
  const [sparkRef, spark] = useMeasuredSize();
  const sorted = [...series.history].sort((a, b) => (a.period < b.period ? -1 : 1));
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  return (
    <div
      data-testid="cash-capital-tile"
      data-metric={series.label}
      className="flex flex-col rounded-md bg-strata-raise px-3 py-2"
    >
      <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-kicker text-strata-dim">
        <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-sm" style={{ backgroundColor: series.color }} />
        {series.label} / share
      </div>
      <div className="mt-1 font-mono text-base font-medium text-strata-hi">
        {usdPerShare(last.value)}
      </div>
      <div className="font-mono text-[10px] text-strata-dim">
        {changeSinceFirst(first.value, last.value)} vs {first.period}
      </div>
      <div ref={sparkRef} data-testid="cash-capital-spark" className="mt-1 flex min-h-[26px] flex-1 items-end overflow-hidden">
        <Sparkline
          history={sorted}
          width={spark ? spark.width : "100%"}
          height={spark ? Math.min(SPARK_MAX_H, Math.max(SPARK_MIN_H, spark.height)) : SPARK_MIN_H}
          color={series.color}
          ariaLabel={`${series.label} per share by quarter`}
        />
      </div>
    </div>
  );
}

export function CashAndCapitalCard({
  capAllocSection,
  qualitySection,
  runwayQuarters,
}: Props) {
  const tiles = [
    ...extractCapexSbcSeries(capAllocSection),
    ...extractCashDebtSeries(qualitySection),
  ].filter((s) => s.history.length >= 2);
  const netCash = extractNetCashPerShare(qualitySection);

  const sign = netCash === null ? "neutral" : netCash >= 0 ? "pos" : "neg";
  const colorClass =
    sign === "pos"
      ? "text-strata-pos"
      : sign === "neg"
        ? "text-strata-neg"
        : "text-strata-hi";

  // Net cash / share is a per-share dollar amount — pass the unit hint
  // explicitly so values < $1 don't render as a percent (Phase 4.3.X).
  const netCashLabel =
    netCash === null ? "—" : formatClaimValue(netCash, "usd_per_share");

  return (
    <section className="flex h-full flex-col rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-cashflow">
        Cash &amp; capital · / share
      </div>

      {tiles.length > 0 && (
        // flex-1 + auto-rows-fr: in a stretched row the tiles share the
        // spare height instead of leaving a blank band under the card.
        <div className="mb-3 grid flex-1 auto-rows-fr grid-cols-2 gap-2">
          {tiles.map((s) => (
            <MetricTile key={s.label} series={s} />
          ))}
        </div>
      )}

      <div
        data-testid="net-cash-highlight"
        data-sign={sign}
        className="flex items-baseline justify-between rounded-md bg-strata-raise px-3 py-2"
      >
        <span className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
          Net cash / share
        </span>
        <span
          className={`font-mono tabular text-lg font-medium ${colorClass}`}
        >
          {netCashLabel}
        </span>
      </div>

      {/* Phase 4.5.B — runway tile. Only renders when the report's
          layout_signals.cash_runway_quarters is non-null (FCF-burning
          companies). Adds a "raise likely needed" sub-line when
          runway < 6Q. Stays hidden for healthy / FCF-positive names. */}
      {runwayQuarters !== null && runwayQuarters !== undefined && (
        <div
          data-testid="cash-runway-tile"
          className="mt-2 flex items-baseline justify-between rounded-md bg-strata-raise px-3 py-2"
        >
          <div className="flex flex-col">
            <span className="font-mono text-[10px] uppercase tracking-kicker text-strata-risk">
              Cash runway
            </span>
            {runwayQuarters < RUNWAY_RAISE_THRESHOLD && (
              <span className="mt-0.5 text-xs text-strata-dim">
                raise likely needed
              </span>
            )}
          </div>
          <span
            className={`font-mono tabular text-lg font-medium ${
              runwayQuarters < RUNWAY_RAISE_THRESHOLD
                ? "text-strata-neg"
                : "text-strata-hi"
            }`}
          >
            ~{runwayQuarters.toFixed(1)}Q
          </span>
        </div>
      )}
    </section>
  );
}
