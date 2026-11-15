/**
 * StrategyBuilder — a template's legs on the chosen expiry, priced from
 * its quotes at mid and at the natural price (buy at the ask, sell at the
 * bid): the cost, the most it makes and loses, breakevens, the
 * risk-neutral probability of profit, and the payoff at expiry. Templates
 * only: strikes start from a fixed rule and can be changed; nothing is
 * ranked or suggested (ADR 0008).
 */
import { useMemo, useState } from "react";

import type { ChainRow, ExpiryChain } from "../../lib/options-schemas";
import {
  type Analysis,
  CONTRACT_SIZE,
  type Leg,
  TEMPLATES,
  type Template,
  analyse,
  oneSigma,
  quoteFor,
  smileOf,
  templateLegs,
} from "../../lib/options-strategy";
import { money, pct } from "./chart-kit";
import { PayoffChart } from "./PayoffChart";

const dash = "—";

function perContract(v: number): string {
  return `$${Math.abs(v * CONTRACT_SIZE).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** A profit or loss with its sign: a best case below zero must read as a loss. */
function signed(v: number): string {
  const rounded = Math.round(v * CONTRACT_SIZE * 100);
  return `${rounded < 0 ? "−" : rounded > 0 ? "+" : ""}${perContract(v)}`;
}

const legName = (leg: Leg) => `${leg.side === 1 ? "Buy" : "Sell"} the ${leg.strike} ${leg.kind}`;

/** Why a leg has no price at mid, or null when it has one. */
function unpriced(leg: Leg, rows: ChainRow[]): string | null {
  const q = quoteFor(rows, leg);
  if (!q || (q.bid <= 0 && q.ask <= 0)) return `${legName(leg)}: no quote at this strike.`;
  if (q.ask <= 0) return `${legName(leg)}: no offer at this strike, so no mid${leg.side === 1 ? " and nothing to buy" : "; it can still be sold at the bid"}.`;
  return null;
}

export function StrategyBuilder({ chain }: { chain: ExpiryChain }) {
  const [template, setTemplate] = useState<Template>("long_call");
  const [legs, setLegs] = useState<Leg[] | null>(() => templateLegs("long_call", chain));
  const smile = useMemo(() => smileOf(chain), [chain]);
  const strikes = useMemo(() => chain.rows.map((r) => r.strike).sort((a, b) => a - b), [chain]);

  const pick = (t: Template) => {
    setTemplate(t);
    setLegs(templateLegs(t, chain));
  };
  const setStrike = (i: number, strike: number) => setLegs((prev) => prev && prev.map((l, j) => (j === i ? { ...l, strike } : l)));

  const mid = legs && analyse(legs, chain.rows, "mid", smile);
  const natural = legs && analyse(legs, chain.rows, "natural", smile);
  const reasons = legs ? legs.map((l) => unpriced(l, chain.rows)).filter((r): r is string => r !== null) : [];
  const sigma = oneSigma(chain);
  const shown = mid ?? natural;

  return (
    <div data-testid="strategy">
      <div role="group" aria-label="Template" className="mb-4 flex flex-wrap gap-2">
        {(Object.keys(TEMPLATES) as Template[]).map((t) => (
          <button
            key={t}
            type="button"
            aria-pressed={t === template}
            onClick={() => pick(t)}
            className={`rounded-md border px-2.5 py-1 font-mono text-[11px] ${
              t === template ? "border-strata-hi text-strata-hi" : "border-strata-border text-strata-dim hover:text-strata-hi"
            }`}
          >
            {TEMPLATES[t]}
          </button>
        ))}
      </div>

      {legs === null ? (
        <p data-testid="strategy-unavailable" className="text-sm text-strata-dim">
          This expiry has no quoted strikes to build a {TEMPLATES[template].toLowerCase()} from.
        </p>
      ) : (
        <>
          <LegsTable legs={legs} rows={chain.rows} strikes={strikes} onStrike={setStrike} />
          {reasons.length > 0 && (
            <p data-testid="strategy-unpriced" className="mt-4 text-sm text-strata-dim">
              {reasons.join(" ")}
            </p>
          )}
          {shown && (
            <div className="mt-5 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.6fr)]">
              <div>
                <Summary mid={mid} natural={natural} />
                {shown.pop === null && (
                  <p data-testid="strategy-no-smile" className="mt-2 font-mono text-[10px] text-strata-muted">
                    No smile at this expiry, so no probability.
                  </p>
                )}
              </div>
              <div className="min-w-0">
                <PayoffChart mid={mid} natural={natural} forward={chain.forward} sigma={sigma} />
              </div>
            </div>
          )}
        </>
      )}

      <p data-testid="strategy-disclaimer" className="mt-4 font-mono text-[10px] text-strata-muted">
        Per contract of {CONTRACT_SIZE} shares, before commissions. The probability is risk-neutral, from this expiry&apos;s
        smile, and counts only the price at expiry: what the market prices, not a forecast or an edge. Strikes start from
        a fixed rule (at the money, half a sigma and a sigma out); a template, not a recommendation. These are American
        options: a short call in the money can be assigned early, most often before an ex-dividend date.
      </p>
    </div>
  );
}

function LegsTable({
  legs,
  rows,
  strikes,
  onStrike,
}: {
  legs: Leg[];
  rows: ChainRow[];
  strikes: number[];
  onStrike: (i: number, strike: number) => void;
}) {
  const cell = "px-2 py-1 text-right";
  return (
    <div className="overflow-x-auto">
      <table className="w-full font-mono text-[11px] tabular-nums">
        <thead className="text-strata-muted">
          <tr className="border-b border-strata-border">
            <th className="px-2 py-1 text-left">Leg</th>
            <th className={cell}>Strike</th>
            <th className={cell}>Bid</th>
            <th className={cell}>Ask</th>
            <th className={cell}>Mid</th>
            <th className={cell}>IV</th>
          </tr>
        </thead>
        <tbody>
          {legs.map((leg, i) => {
            const row = rows.find((r) => r.strike === leg.strike);
            const q = quoteFor(rows, leg);
            const iv = row ? (leg.kind === "call" ? row.call_iv : row.put_iv) : null;
            return (
              <tr key={i} data-testid="strategy-leg" className="border-b border-strata-border/40">
                <td className="px-2 py-1 text-left text-strata-hi">
                  {leg.side === 1 ? "Buy" : "Sell"} {leg.kind}
                </td>
                <td className={cell}>
                  <select
                    data-testid="strategy-leg-strike"
                    aria-label={`Strike, leg ${i + 1}`}
                    value={String(leg.strike)}
                    onChange={(e) => onStrike(i, Number(e.target.value))}
                    className="rounded border border-strata-border bg-strata-canvas px-1 py-0.5 text-strata-fg"
                  >
                    {strikes.map((k) => (
                      <option key={k} value={String(k)}>
                        {k}
                      </option>
                    ))}
                  </select>
                </td>
                <td className={cell}>{q && q.bid > 0 ? q.bid.toFixed(2) : dash}</td>
                <td className={cell}>{q && q.ask > 0 ? q.ask.toFixed(2) : dash}</td>
                <td className={cell}>{q && q.ask > 0 ? ((q.bid + q.ask) / 2).toFixed(2) : dash}</td>
                <td className={cell}>{iv === null ? dash : pct(iv)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Summary({ mid, natural }: { mid: Analysis | null; natural: Analysis | null }) {
  const net = (a: Analysis) => `${a.cost >= 0 ? "Debit" : "Credit"} ${perContract(a.cost)}`;
  const cap = (v: number | null) => (v === null ? "Unlimited" : signed(v));
  const evens = (a: Analysis) => (a.breakevens.length ? a.breakevens.map(money).join(", ") : "None");
  const rows: [string, (a: Analysis) => string][] = [
    ["Net", net],
    ["Max profit", (a) => cap(a.maxProfit)],
    ["Max loss", (a) => cap(a.maxLoss)],
    ["Breakevens", evens],
    ["Probability of profit", (a) => (a.pop === null ? dash : pct(a.pop, 0))],
  ];
  return (
    <table data-testid="strategy-summary" className="w-full self-start font-mono text-[11px] tabular-nums">
      <thead className="text-strata-muted">
        <tr className="border-b border-strata-border">
          <th />
          <th className="px-2 py-1 text-right">At mid</th>
          <th className="px-2 py-1 text-right">At the natural price</th>
        </tr>
      </thead>
      <tbody>
        {rows.map(([label, value]) => (
          <tr key={label} className="border-b border-strata-border/40">
            <td className="py-1 pr-2 text-strata-dim">{label}</td>
            <td className="px-2 py-1 text-right text-strata-hi">{mid ? value(mid) : dash}</td>
            <td className="px-2 py-1 text-right text-strata-fg">{natural ? value(natural) : dash}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
