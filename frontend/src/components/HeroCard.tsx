/**
 * HeroCard — top-of-dashboard headline card. Phase 4.1.
 *
 * Three columns:
 *   left:   ticker meta (logo placeholder, ticker eyebrow, sector
 *           tag, name, big tabular price, delta, MCAP/VOL/52W meta)
 *   center: 60-day price chart with 1D/5D/1M/3M/1Y/5Y range pills
 *   right:  3 featured stats (Forward P/E, ROIC TTM, FCF Margin) with
 *           peer/historical sub-context where available
 *
 * Reads:
 *   - `report.name` / `report.sector` (top-level, Phase 4.1)
 *   - claim values via `extractHeroData`
 *   - prices via `fetchMarketPrices` (TanStack Query)
 *
 * The Strata design renders a faint radial-gradient glow at the top-
 * right matching the accent color. We do that via a backgroundImage
 * inline style since it's the only place in the UI that does this.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchMarketPrices } from "../lib/api";
import { formatClaimValue } from "../lib/format";
import { extractHeroData } from "../lib/hero-extract";
import type { ResearchReport } from "../lib/schemas";
import { LineChart } from "./LineChart";

interface Props {
  report: ResearchReport;
}

const RANGES = ["1D", "5D", "1M", "3M", "1Y", "5Y"] as const;
type Range = (typeof RANGES)[number];

// Backend currently accepts 60D / 1Y / 5Y; map UI ranges accordingly.
// Phase 4.1 doesn't add 1D/5D/1M/3M intraday; the pills exist for
// design fidelity but coerce to the closest backend-supported value.
function backendRangeFor(uiRange: Range): "60D" | "1Y" | "5Y" {
  if (uiRange === "1Y" || uiRange === "5Y") return uiRange;
  // 1D / 5D / 1M / 3M all coerce to 60D for now (the backend doesn't
  // support intraday cadence yet — that's Phase 4.7+).
  return "60D";
}

function formatPrice(n: number): string {
  return n.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatLargeNumber(n: number): string {
  // Used for the MCAP / VOL / 52W meta strip. MCAP comes through as
  // already-USD; this wrapper preserves the legacy heuristic for the
  // pre-Phase-4.1 cached rows (the heuristic correctly abbreviates
  // 4.11e12 → "4.11T" without the $ prefix). Hero's market-cap stat
  // uses formatClaimValue with explicit unit when the claim's unit is
  // available (post-4.3.X cache rows).
  return formatClaimValue(n);
}

function logoLetter(symbol: string): string {
  return (symbol[0] ?? "?").toUpperCase();
}

export function HeroCard({ report }: Props) {
  const hero = extractHeroData(report);
  const symbol = report.symbol;
  const [range, setRange] = useState<Range>("3M");

  const pricesQuery = useQuery({
    queryKey: ["prices", symbol, backendRangeFor(range)],
    queryFn: () => fetchMarketPrices(symbol, backendRangeFor(range)),
    staleTime: 60_000,
  });

  const latest = pricesQuery.data?.latest;
  const isUp = (latest?.delta_abs ?? 0) >= 0;
  const deltaClass = isUp ? "text-strata-pos" : "text-strata-neg";
  const deltaSign = isUp ? "+" : "";

  const meta: string[] = [];
  if (hero?.marketCap) meta.push(`MCAP ${formatLargeNumber(hero.marketCap)}`);
  if (latest)
    meta.push(`VOL ${formatLargeNumber(pricesQuery.data?.prices.at(-1)?.volume ?? 0)}`);
  if (hero?.fiftyTwoWeekHigh && hero?.fiftyTwoWeekLow) {
    meta.push(
      `52W ${formatPrice(hero.fiftyTwoWeekLow)} — ${formatPrice(hero.fiftyTwoWeekHigh)}`,
    );
  }

  return (
    <div
      className="mb-6 rounded-xl border border-strata-border bg-strata-surface p-7 shadow-[0_24px_60px_-28px_rgba(126,154,212,0.25)]"
      style={{
        backgroundImage:
          "radial-gradient(1200px 600px at 80% -10%, rgba(126,154,212,0.08), transparent 60%)",
      }}
    >
      <div className="grid grid-cols-1 gap-9 md:grid-cols-[1.2fr_2fr_0.9fr] md:items-center">
        {/* ── LEFT: ticker meta ── */}
        <div>
          <div className="mb-3 flex items-center gap-3">
            <div
              aria-label={`${symbol} logo placeholder`}
              className="flex h-10 w-10 items-center justify-center rounded-lg bg-strata-highlight font-mono text-sm font-bold text-strata-canvas"
            >
              {logoLetter(symbol)}
            </div>
            <div className="flex flex-col">
              {/*
                Phase 4.3.X — exchange chip (cosmetic backlog from PR
                #50). Combines ticker + sector token into one chip
                matching the design's "NVDA · NASDAQ · SEMIS" treatment.
                We don't carry exchange data yet — sector_tag stands in
                until ``fetch_fundamentals`` adds an ``exchange`` claim.
              */}
              <div
                data-testid="hero-exchange-chip"
                className="inline-flex items-center gap-1.5 font-mono text-xs uppercase tracking-kicker"
              >
                <span className="text-strata-highlight">{symbol}</span>
                {hero?.sector && (
                  <>
                    <span aria-hidden className="text-strata-line">·</span>
                    <span className="text-strata-dim">{hero.sector}</span>
                  </>
                )}
              </div>
            </div>
          </div>
          {hero?.name && (
            <div className="mb-3 text-2xl font-medium tracking-tight text-strata-hi">
              {hero.name}
            </div>
          )}
          <div className="flex items-baseline gap-3">
            <span className="font-mono tabular text-4xl font-medium tracking-tight text-strata-hi">
              {latest ? formatPrice(latest.close) : "—"}
            </span>
            {latest && (
              <span className={`font-mono text-sm ${deltaClass}`}>
                {deltaSign}
                {formatPrice(latest.delta_abs)}{" "}
                <span className="opacity-70">
                  ({deltaSign}
                  {(latest.delta_pct * 100).toFixed(2)}%)
                </span>
              </span>
            )}
          </div>
          {meta.length > 0 && (
            <div className="mt-3 font-mono text-xs uppercase tracking-wide text-strata-dim">
              {meta.join(" · ")}
            </div>
          )}
        </div>

        {/* ── CENTER: chart + range pills ── */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="font-mono text-[10px] uppercase tracking-kicker text-strata-highlight">
              Price · {range === "3M" ? "60 trading days" : range}
            </span>
            <div className="flex gap-1 font-mono text-xs">
              {RANGES.map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => setRange(r)}
                  className={`rounded px-2 py-0.5 transition ${
                    r === range
                      ? "bg-strata-highlight text-strata-canvas"
                      : "text-strata-dim hover:text-strata-fg"
                  }`}
                >
                  {r}
                </button>
              ))}
            </div>
          </div>
          {pricesQuery.isPending ? (
            <div
              data-testid="line-chart-loading"
              className="flex h-[140px] w-full items-center justify-center rounded-md border border-strata-line bg-strata-canvas/40 font-mono text-[10px] uppercase tracking-kicker text-strata-muted"
            >
              Loading chart…
            </div>
          ) : pricesQuery.data?.prices.length ? (
            <LineChart
              data={pricesQuery.data.prices}
              areaFill={true}
              ariaLabel={`${symbol} price chart, ${range}`}
            />
          ) : (
            <div className="flex h-[140px] w-full items-center justify-center font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
              No price data available
            </div>
          )}
        </div>

        {/* ── RIGHT: 3 featured stats ── */}
        <div className="flex flex-col gap-4 border-l border-strata-line pl-6">
          {hero?.forwardPE && (
            <FeaturedStat
              label="Forward P/E"
              value={`${hero.forwardPE.value.toFixed(1)}×`}
              sub={
                hero.forwardPE.peerMedian
                  ? `peer median ${hero.forwardPE.peerMedian.toFixed(1)}×`
                  : null
              }
              accentClass="text-strata-valuation"
            />
          )}
          {hero?.roicTTM !== null && hero?.roicTTM !== undefined && (
            <FeaturedStat
              label="ROIC TTM"
              value={formatClaimValue(hero.roicTTM, "fraction")}
              sub={hero.roicTTM > 0.4 ? "top decile" : null}
              accentClass="text-strata-quality"
            />
          )}
          {hero?.fcfMargin !== null && hero?.fcfMargin !== undefined && (
            <FeaturedStat
              label="FCF margin"
              value={formatClaimValue(hero.fcfMargin, "fraction")}
              sub={null}
              accentClass="text-strata-cashflow"
            />
          )}
        </div>
      </div>
    </div>
  );
}

function FeaturedStat({
  label,
  value,
  sub,
  accentClass,
}: {
  label: string;
  value: string;
  sub: string | null;
  accentClass: string;
}) {
  return (
    <div>
      <div
        className={`font-mono text-[10px] uppercase tracking-kicker ${accentClass}`}
      >
        {label}
      </div>
      <div className="mt-1 font-mono tabular text-xl font-medium text-strata-hi">
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-strata-dim">{sub}</div>}
    </div>
  );
}
