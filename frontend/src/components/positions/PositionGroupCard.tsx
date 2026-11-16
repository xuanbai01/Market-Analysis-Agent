/**
 * One underlying's positions: the legs at tastytrade's live marks, their
 * Greeks in dollars, the payoff with a what-if, and what our own data says
 * around them (the chance of profit option prices imply, how often history
 * moved that far, a report before expiry, max pain and the walls). Context
 * comes from the options page's own routes, shared through the query cache.
 * Every sentence is written in code; none advises.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { ApiError, fetchMarketPrices } from "../../lib/api";
import { fetchOptionsChain, fetchOptionsReport } from "../../lib/options-api";
import { smileOf } from "../../lib/options-strategy";
import { dateLabel, maxPainSentence, strikeLabel } from "../../lib/options-text";
import type { PositionGroup, PositionLeg } from "../../lib/owner-schemas";
import {
  type Market,
  NO_CHANGE,
  type Scenario,
  costBasis,
  firstExpiry,
  greeks,
  historicalShare,
  markValue,
  modelled,
  pnlInScenario,
  profitChance,
  sessionsUntil,
  yearsTo,
} from "../../lib/positions-math";
import {
  earningsSentence,
  greeksSentence,
  groupSentence,
  historySentence,
  legLabel,
  marketSentence,
  scenarioSentence,
  signedUsd,
} from "../../lib/positions-text";
import { ROUTES } from "../../lib/routes";
import { SentenceText } from "../options/chart-kit";
import { PositionPayoffChart } from "./PositionPayoffChart";

const FIVE_MINUTES = 5 * 60_000;
const AN_HOUR = 60 * 60_000;

function age(updatedAt: string | null, now: Date): string {
  if (!updatedAt) return "no time";
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(updatedAt).getTime()) / 1000));
  if (seconds < 90) return `${seconds}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

const num = (v: number | null | undefined, digits = 2) => (v === null || v === undefined ? "—" : v.toFixed(digits));

function LegsTable({ legs, now }: { legs: PositionLeg[]; now: Date }) {
  return (
    <div className="overflow-x-auto">
      <table className="mb-3 w-full min-w-[520px] font-mono text-xs" data-testid="position-legs">
        <thead className="text-left text-[10px] uppercase tracking-kicker text-strata-muted">
          <tr>
            <th className="py-1 pr-3 font-normal">Position</th>
            <th className="py-1 pr-3 text-right font-normal">Opened at</th>
            <th className="py-1 pr-3 text-right font-normal">Mark</th>
            <th className="py-1 pr-3 text-right font-normal">P&amp;L</th>
            <th className="py-1 pr-3 text-right font-normal">IV</th>
            <th className="py-1 text-right font-normal">Quote</th>
          </tr>
        </thead>
        <tbody>
          {legs.map((leg) => {
            const mark = leg.quote?.mark ?? null;
            const pnl = mark === null || leg.average_open === null ? null : (mark - leg.average_open) * leg.quantity * leg.multiplier;
            return (
              <tr key={`${leg.account}-${leg.symbol}`} className="border-t border-strata-line text-strata-fg">
                <td className="py-1 pr-3">{legLabel(leg)}</td>
                <td className="py-1 pr-3 text-right">{num(leg.average_open)}</td>
                <td className="py-1 pr-3 text-right">{num(mark)}</td>
                <td className={`py-1 pr-3 text-right ${pnl === null ? "" : pnl >= 0 ? "text-strata-pos" : "text-strata-neg"}`}>{pnl === null ? "—" : signedUsd(pnl)}</td>
                <td className="py-1 pr-3 text-right">{leg.quote?.iv == null ? "—" : `${(leg.quote.iv * 100).toFixed(1)}%`}</td>
                <td className="py-1 text-right text-strata-muted">{leg.quote ? age(leg.quote.updated_at, now) : "none"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Slider({ label, value, min, max, step, onChange, format }: {
  label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; format: (v: number) => string;
}) {
  return (
    <label className="flex min-w-[9rem] flex-1 flex-col gap-1 font-mono text-[11px] text-strata-dim">
      <span>
        {label}: <span className="text-strata-hi">{format(value)}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={value} onChange={(e) => onChange(Number(e.target.value))} aria-label={label} />
    </label>
  );
}

const signedPct = (v: number) => `${v > 0 ? "+" : ""}${Math.round(v * 100)}%`;
const signedPts = (v: number) => `${v > 0 ? "+" : ""}${Math.round(v * 100)} pts`;

function Line({ sentence, testId }: { sentence: ReturnType<typeof marketSentence>; testId: string }) {
  if (!sentence) return null;
  return (
    <p data-testid={testId} className="text-sm leading-relaxed text-strata-fg">
      <SentenceText sentence={sentence} />
    </p>
  );
}

const UNTRACKED = "untracked";
/** Underlyings whose option context a page load reads: each cold read
 * spends one of the IP's options lookups an hour (60). */
export const MAX_CONTEXT = 10;

export function PositionGroupCard({ group, now, withContext }: { group: PositionGroup; now: Date; withContext: boolean }) {
  const expiry = firstExpiry(group);
  const hasOptions = expiry !== null;
  const reads = hasOptions && withContext;
  // Keys of its own: under the options page's, a visit there would be
  // served this untracked copy and never record the view.
  const report = useQuery({
    queryKey: ["options", group.symbol, UNTRACKED],
    queryFn: () => fetchOptionsReport(group.symbol, { track: false }), // a holding isn't a view
    staleTime: FIVE_MINUTES,
    enabled: reads,
    retry: false,
  });
  const chain = useQuery({
    queryKey: ["options-chain", group.symbol, expiry, UNTRACKED],
    queryFn: () => fetchOptionsChain(group.symbol, expiry as string, { track: false }),
    staleTime: FIVE_MINUTES,
    // After the report: it reads several expiries, often the held one, which is then no new lookup.
    enabled: reads && report.isSuccess,
    retry: false,
  });
  const prices = useQuery({
    queryKey: ["prices", group.symbol, "5Y"],
    queryFn: () => fetchMarketPrices(group.symbol, "5Y"),
    staleTime: AN_HOUR,
    enabled: reads,
    retry: false,
  });
  const [scenario, setScenario] = useState<Scenario>(NO_CHANGE);

  const spot = group.quote?.mark || report.data?.spot || null; // a mark of 0 (a halted stock) is no price
  const rate = report.data?.rate ?? 0;
  const yahooSpot = report.data?.spot ?? null;
  const chainData = chain.data ?? null;
  const carry =
    chainData && yahooSpot && chainData.days > 0 ? Math.log(chainData.forward / yahooSpot) / (chainData.days / 365) : rate;
  const market: Market | null = spot === null ? null : { spot, rate, carry, now };
  const value = markValue(group);
  const cost = costBasis(group);
  const g = spot === null ? null : greeks(group, spot);
  const smile = chainData ? smileOf(chainData) : null;
  const sigma = chainData?.atm_iv && expiry ? chainData.atm_iv * Math.sqrt(yearsTo(expiry, now, group.legs)) : null;
  const sessions = expiry ? sessionsUntil(expiry, now, group.legs) : 0;
  const closes = prices.data?.prices.map((p) => p.close) ?? [];
  const daysLeft = expiry ? Math.max(0, Math.floor(yearsTo(expiry, now, group.legs) * 365)) : 0;
  const spread = group.expiries.length > 1;
  const maxPain = chainData?.positioning ? maxPainSentence(chainData.positioning, spot) : null;
  // A route that failed leaves gaps in the card: say so rather than drop them quietly.
  const contextError = [report.error, chain.error].find((e) => e && !(e instanceof ApiError && e.status === 401));

  return (
    <section data-testid="position-group" className="mb-6 min-w-0 rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-mono text-sm text-strata-hi">{group.underlying}</h2>
        {hasOptions && (
          <Link to={ROUTES.options(group.symbol)} className="font-mono text-[11px] text-strata-highlight hover:underline">
            {group.symbol} options →
          </Link>
        )}
      </div>
      <p className="mb-3 text-sm leading-relaxed text-strata-fg" data-testid="position-group-summary">
        <SentenceText sentence={groupSentence(group, value, cost)} />
      </p>
      <LegsTable legs={group.legs} now={now} />
      {g && <Line sentence={greeksSentence(g)} testId="position-greeks" />}
      {!modelled(group) && (
        <p className="mt-2 text-xs text-strata-dim">An adjusted contract (not 100 plain shares) is listed but not modelled, so this position has no payoff chart.</p>
      )}
      {market && modelled(group) && (
        <div className="mt-4">
          <PositionPayoffChart group={group} market={market} scenario={scenario} sigma={sigma} />
          <div className="mt-3 flex flex-wrap gap-4" data-testid="position-whatif">
            <Slider label={`${group.underlying} moves`} value={scenario.move} min={-0.3} max={0.3} step={0.01} format={signedPct} onChange={(move) => setScenario({ ...scenario, move })} />
            <Slider label="IV changes" value={scenario.ivShift} min={-0.2} max={0.2} step={0.01} format={signedPts} onChange={(ivShift) => setScenario({ ...scenario, ivShift })} />
            {daysLeft > 0 && (
              <Slider label="Days pass" value={scenario.days} min={0} max={daysLeft} step={1} format={(d) => `${d}`} onChange={(days) => setScenario({ ...scenario, days })} />
            )}
          </div>
          <p className="mt-2 text-sm text-strata-fg" data-testid="position-whatif-summary">
            <SentenceText sentence={scenarioSentence(group.underlying, scenario, market.spot * (1 + scenario.move), pnlInScenario(group, scenario, market))} />
          </p>
        </div>
      )}
      <div className="mt-4 space-y-2">
        {hasOptions && !withContext && (
          <p data-testid="position-context-skipped" className="text-xs text-strata-dim">
            Option context (the chance of profit, past moves, max pain, the walls) is read for the first {MAX_CONTEXT} underlyings
            only, to stay within the hour&rsquo;s option lookups.
          </p>
        )}
        {contextError && (
          <p data-testid="position-context-missing" className="text-xs text-strata-dim">
            {group.underlying}&rsquo;s option data couldn&rsquo;t be read (
            {contextError instanceof ApiError ? contextError.title : "no answer"}), so the chance of profit, max pain and the walls are left out.
          </p>
        )}
        {market && <Line sentence={marketSentence(smile ? profitChance(group, smile, market) : null, expiry, spread)} testId="position-market" />}
        {market && expiry && <Line sentence={historySentence(group.underlying, historicalShare(group, closes, sessions, market), sessions)} testId="position-history" />}
        <Line sentence={earningsSentence(group.underlying, report.data?.earnings ?? null, expiry)} testId="position-earnings" />
        {maxPain && expiry && <Line sentence={[`${dateLabel(expiry)}: `, ...maxPain]} testId="position-maxpain" />}
        {chainData?.positioning && (chainData.positioning.call_wall !== null || chainData.positioning.put_wall !== null) && (
          <p className="text-xs text-strata-dim" data-testid="position-walls">
            Walls: {chainData.positioning.call_wall !== null ? `calls ${strikeLabel(chainData.positioning.call_wall)}` : ""}
            {chainData.positioning.call_wall !== null && chainData.positioning.put_wall !== null ? ", " : ""}
            {chainData.positioning.put_wall !== null ? `puts ${strikeLabel(chainData.positioning.put_wall)}` : ""}. {chainData.positioning.assumption}
          </p>
        )}
      </div>
    </section>
  );
}
