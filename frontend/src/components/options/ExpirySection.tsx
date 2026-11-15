/**
 * ExpirySection — pick an expiry; see its smile, open interest by strike
 * and the near-the-money chain, and build a strategy on it. The report
 * carries the expiry nearest 30 days; any other is read on demand
 * (/v1/options/{symbol}/chain/{expiry}).
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { fetchOptionsChain } from "../../lib/options-api";
import type { ChainRow, ExpiryChain } from "../../lib/options-schemas";
import { ErrorBanner } from "../ErrorBanner";
import { pct, shortDate } from "./chart-kit";
import { OpenInterestChart } from "./OpenInterestChart";
import { Panel } from "./Panel";
import { SmileChart } from "./SmileChart";
import { StrategyBuilder } from "./StrategyBuilder";
import { useSignOutOn401 } from "./useSignOutOn401";

interface Props {
  symbol: string;
  listed: string[];
  initial: ExpiryChain;
  spot: number | null;
}

const dash = "—";
// A zero bid beside an offer is a price (nobody bids); a zero ask is no
// offer at all, so a dash, as is a bid where neither side quotes.
const bid = (v: number, ask: number) => (v > 0 || ask > 0 ? v.toFixed(2) : dash);
const ask = (v: number) => (v > 0 ? v.toFixed(2) : dash);
const iv = (v: number | null) => (v === null ? dash : pct(v));
const delta = (v: number | null) => (v === null ? dash : v.toFixed(2));
const strike = (k: number) => (Number.isInteger(k) ? k.toFixed(0) : k.toFixed(2));

export function ExpirySection({ symbol, listed, initial, spot }: Props) {
  // The report's expiry unless the reader picked another that is still
  // listed: a refetch that rolls the report's expiry forward is followed.
  const [picked, setPicked] = useState<string | null>(null);
  const expiry = picked !== null && listed.includes(picked) ? picked : initial.expiry;
  const query = useQuery({
    queryKey: ["options-chain", symbol, expiry],
    queryFn: () => fetchOptionsChain(symbol, expiry),
    enabled: expiry !== initial.expiry,
    staleTime: 5 * 60_000,
  });
  const chain = expiry === initial.expiry ? initial : query.data;
  const unauthorized = useSignOutOn401(query.error);
  // An error belongs to an expiry read on demand; once the report's own
  // chain is that expiry, it no longer applies.
  const failed = expiry !== initial.expiry && !unauthorized ? query.error : null;

  return (
    <>
      <Panel title="One expiry">
        <div data-testid="options-expiry-section">
          <label className="mb-4 flex items-center gap-2 font-mono text-[11px] text-strata-dim">
            Expiry
            <select
              data-testid="options-expiry-select"
              value={expiry}
              onChange={(e) => setPicked(e.target.value)}
              className="rounded-md border border-strata-border bg-strata-canvas px-2 py-1 text-strata-fg"
            >
              {listed.map((d) => (
                <option key={d} value={d}>
                  {shortDate(d, true)}
                </option>
              ))}
            </select>
            {chain && <span>{Math.round(chain.days)} days · forward ${chain.forward.toFixed(2)}</span>}
          </label>
          {query.isFetching && <p className="font-mono text-[11px] text-strata-muted">Reading {shortDate(expiry, true)}…</p>}
          {failed && <ErrorBanner error={failed} />}
          {chain && (
            <>
              <div className="grid gap-6 lg:grid-cols-2">
                <div className="min-w-0">
                  <SmileChart chain={chain} />
                </div>
                <div className="min-w-0">
                  <OpenInterestChart chain={chain} spot={spot} />
                </div>
              </div>
              <ChainTable chain={chain} />
            </>
          )}
        </div>
      </Panel>
      {chain && (
        <Panel title={`Strategy, ${shortDate(chain.expiry, true)} expiry`} testId="options-strategy-panel">
          {/* Keyed on the expiry: a new chain starts its template over. */}
          <StrategyBuilder key={chain.expiry} chain={chain} />
        </Panel>
      )}
    </>
  );
}

function ChainTable({ chain }: { chain: ExpiryChain }) {
  if (chain.rows.length === 0) return null;
  const atm = chain.rows.reduce((best, r) => (Math.abs(r.strike - chain.forward) < Math.abs(best.strike - chain.forward) ? r : best));
  const cell = "px-2 py-1 text-right";
  const side = (r: ChainRow, call: boolean) => {
    const usable = call ? r.call_usable : r.put_usable;
    const values = call
      ? [bid(r.call_bid, r.call_ask), ask(r.call_ask), iv(r.call_iv), delta(r.call_delta), r.call_open_interest.toLocaleString("en-US"), r.call_volume.toLocaleString("en-US")]
      : [bid(r.put_bid, r.put_ask), ask(r.put_ask), iv(r.put_iv), delta(r.put_delta), r.put_open_interest.toLocaleString("en-US"), r.put_volume.toLocaleString("en-US")];
    const ids = ["bid", "ask", "iv"];
    return values.map((v, i) => (
      <td
        key={i}
        className={`${cell} ${usable ? "text-strata-fg" : "text-strata-muted"}`}
        data-testid={i < ids.length ? `options-chain-${call ? "call" : "put"}-${ids[i]}` : undefined}
      >
        {v}
      </td>
    ));
  };
  const heads = ["Bid", "Ask", "IV", "Δ", "OI", "Vol"];
  return (
    <div className="mt-6 overflow-x-auto">
      <table data-testid="options-chain-table" className="w-full font-mono text-[11px] tabular-nums">
        <thead className="text-strata-muted">
          <tr>
            <th colSpan={6} className="pb-1 text-center">Calls</th>
            <th />
            <th colSpan={6} className="pb-1 text-center">Puts</th>
          </tr>
          <tr className="border-b border-strata-border">
            {heads.map((h) => <th key={`c${h}`} className={cell}>{h}</th>)}
            <th className="px-3 py-1 text-center">Strike</th>
            {heads.map((h) => <th key={`p${h}`} className={cell}>{h}</th>)}
          </tr>
        </thead>
        <tbody>
          {chain.rows.map((r) => (
            <tr
              key={r.strike}
              data-testid="options-chain-row"
              data-atm={r === atm ? "true" : "false"}
              className={r === atm ? "bg-strata-raise" : "border-b border-strata-border/40"}
            >
              {side(r, true)}
              <td data-testid="options-chain-strike" className="px-3 py-1 text-center text-strata-hi">
                {strike(r.strike)}
              </td>
              {side(r, false)}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 font-mono text-[10px] text-strata-muted">
        Grey: no two-sided quote within the spread rule, so no IV. Δ is forward delta from the smile.
      </p>
    </div>
  );
}
