/**
 * ComparePriceChart — both tickers' price over the same ~3 months, as
 * % change from the first close, on one axis (2026-11 chart audit).
 *
 * Each hero card used to carry its own mini area chart with its own
 * unlabelled y-scale, so a 12% range filled the box as fully as a 3%
 * one: KO "soared" beside an NVDA that "crashed". Rebasing both to 0%
 * on one scale makes the two moves comparable.
 */
import { useQuery } from "@tanstack/react-query";

import { fetchMarketPrices } from "../../lib/api";
import { fractionPctTick } from "../../lib/chart-format";
import { COMPARE_COLOR_A, COMPARE_COLOR_B } from "../../lib/compare-extract";
import type { PricePoint } from "../../lib/schemas";
import { MultiLine, type MultiLineSeries } from "../MultiLine";

interface Props {
  a: string;
  b: string;
}

const RANGE = "60D" as const;

/** Close-to-close % change from the first close, keyed by day. */
export function toReturnSeries(
  symbol: string,
  prices: readonly PricePoint[] | undefined,
  color: string,
): MultiLineSeries | null {
  if (!prices || prices.length < 2) return null;
  const first = prices[0].close;
  if (!(first > 0)) return null;
  return {
    label: symbol,
    shortLabel: symbol,
    color,
    history: prices.map((p) => ({ period: p.ts.slice(0, 10), value: p.close / first - 1 })),
  };
}

function signedPct(v: number): string {
  return `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

/** "2026-08-14" → "Aug 14". */
function dayLabel(period: string): string {
  const d = new Date(`${period}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return period;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
}

export function ComparePriceChart({ a, b }: Props) {
  const qa = useQuery({
    queryKey: ["prices", a, RANGE],
    queryFn: () => fetchMarketPrices(a, RANGE),
    staleTime: 60_000,
  });
  const qb = useQuery({
    queryKey: ["prices", b, RANGE],
    queryFn: () => fetchMarketPrices(b, RANGE),
    staleTime: 60_000,
  });

  const series = [
    toReturnSeries(a, qa.data?.prices, COMPARE_COLOR_A),
    toReturnSeries(b, qb.data?.prices, COMPARE_COLOR_B),
  ].filter((s): s is MultiLineSeries => s !== null);

  return (
    <section data-testid="compare-price-chart" className="rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-highlight">
        Price · 3 months · % change from the first close
      </div>
      {series.length > 0 ? (
        <MultiLine
          series={series}
          height={200}
          baseline={0}
          formatValue={signedPct}
          formatTick={fractionPctTick}
          formatPeriod={dayLabel}
          ariaLabel={`${a} and ${b} price, % change over 3 months`}
        />
      ) : (
        <div className="flex h-[200px] items-center justify-center font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
          {qa.isPending || qb.isPending ? "Loading…" : "No price data"}
        </div>
      )}
    </section>
  );
}
