/**
 * CompareHero — Phase 4.6.A.
 *
 * Two ticker cards side-by-side with a "VS" badge between them. Each
 * card shows ticker + sector chip + name + price + delta + market cap
 * + a mini area chart in the side's accent color.
 *
 * The card itself is intentionally simpler than the symbol-detail
 * HeroCard: no range-pill sub-controls, no axes/tooltip, no featured-
 * stat trio. The Compare page foregrounds the side-by-side metric
 * rows, not per-side ornament.
 */
import { useQuery } from "@tanstack/react-query";

import { fetchMarketPrices } from "../../lib/api";
import {
  COMPARE_COLOR_A,
  COMPARE_COLOR_B,
  type CompareHeroData,
} from "../../lib/compare-extract";
import { formatClaimValue } from "../../lib/format";
import type { LayoutSignals } from "../../lib/schemas";
import { HeaderPills } from "../HeaderPills";
import { LineChart } from "../LineChart";

interface CompareHeroColumnProps {
  side: "a" | "b";
  hero: CompareHeroData;
  signals: LayoutSignals;
}

interface Props {
  a: CompareHeroData;
  b: CompareHeroData;
  signalsA: LayoutSignals;
  signalsB: LayoutSignals;
}

function formatPrice(n: number): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function CompareHeroColumn({ side, hero, signals }: CompareHeroColumnProps) {
  const accent = side === "a" ? COMPARE_COLOR_A : COMPARE_COLOR_B;
  const pricesQuery = useQuery({
    queryKey: ["prices", hero.symbol, "60D"],
    queryFn: () => fetchMarketPrices(hero.symbol, "60D"),
    staleTime: 60_000,
  });

  const latest = pricesQuery.data?.latest;
  const isUp = (latest?.delta_abs ?? 0) >= 0;
  const deltaSign = isUp ? "+" : "";

  return (
    <div
      data-card="compare-hero"
      data-ticker={hero.symbol}
      data-side={side}
      className="rounded-md border border-strata-border bg-strata-surface p-5"
    >
      <div className="mb-2 flex items-start justify-between">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-highlight">
            {hero.symbol}
            {hero.sector && (
              <>
                <span className="mx-1 text-strata-line">·</span>
                <span className="text-strata-dim">{hero.sector}</span>
              </>
            )}
          </div>
          {hero.name && (
            <div className="mt-1 text-xl font-medium tracking-tight text-strata-hi">
              {hero.name}
            </div>
          )}
        </div>
        <HeaderPills signals={signals} />
      </div>

      <div className="mt-2 flex items-baseline gap-2">
        <span className="font-mono tabular text-3xl font-medium tracking-tight text-strata-hi">
          {latest ? formatPrice(latest.close) : "—"}
        </span>
        {latest && (
          <span
            className={`font-mono text-xs ${isUp ? "text-strata-pos" : "text-strata-neg"}`}
          >
            {deltaSign}
            {formatPrice(latest.delta_abs)}{" "}
            <span className="opacity-70">
              ({deltaSign}
              {(latest.delta_pct * 100).toFixed(2)}%)
            </span>
          </span>
        )}
      </div>

      {hero.marketCap && (
        <div className="mt-1 font-mono text-xs uppercase tracking-wide text-strata-dim">
          MCAP {formatClaimValue(hero.marketCap)}
        </div>
      )}

      <div className="mt-4">
        {pricesQuery.data?.prices.length ? (
          <LineChart
            data={pricesQuery.data.prices}
            strokeColor={accent}
            fillColor={accent}
            areaFill={true}
            ariaLabel={`${hero.symbol} price chart, 60D`}
            height={120}
          />
        ) : (
          <div className="flex h-[120px] w-full items-center justify-center font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
            {pricesQuery.isPending ? "Loading…" : "No price data"}
          </div>
        )}
      </div>
    </div>
  );
}

export function CompareHero({ a, b, signalsA, signalsB }: Props) {
  return (
    <div className="relative grid grid-cols-1 items-stretch gap-4 lg:grid-cols-2">
      <CompareHeroColumn side="a" hero={a} signals={signalsA} />
      <CompareHeroColumn side="b" hero={b} signals={signalsB} />
      {/* The "VS" badge sits between the two cards on lg+. Hidden on
          stacked mobile to avoid a floating glyph mid-page. */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-1/2 hidden -translate-x-1/2 -translate-y-1/2 rounded-full border border-strata-border bg-strata-surface px-2 py-1 font-mono text-[10px] uppercase tracking-kicker text-strata-dim lg:block"
      >
        vs
      </div>
    </div>
  );
}
