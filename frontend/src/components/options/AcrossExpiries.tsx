/**
 * AcrossExpiries — each expiry the report reads, in a row: its kind and
 * days, max pain and how far that is from the price, net gamma exposure,
 * and put/call open interest.
 */
import type { ExpirySummary } from "../../lib/options-schemas";
import { compactUsd, daysLabel, expiryKind } from "../../lib/options-text";
import { money, pct, shortDate } from "./chart-kit";

export function drawsAcross(expiries: ExpirySummary[]): boolean {
  return expiries.some((e) => e.max_pain !== null);
}

export function AcrossExpiries({ expiries, price }: { expiries: ExpirySummary[]; price: number | null }) {
  const rows = [...expiries].sort((a, b) => a.days - b.days);
  if (!drawsAcross(rows)) return null;
  const cell = "px-2 py-1 text-right";
  return (
    <div className="overflow-x-auto">
      <table data-testid="options-across" className="w-full font-mono text-[11px] tabular-nums">
        <thead className="text-strata-muted">
          <tr className="border-b border-strata-border">
            <th className="px-2 py-1 text-left">Expiry</th>
            <th className={cell}>Days</th>
            <th className={cell}>Max pain</th>
            <th className={cell}>vs price</th>
            <th className={cell}>Net gamma, per 1%</th>
            <th className={cell}>Put/call OI</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((e) => {
            const gap = e.max_pain !== null && price ? e.max_pain - price : null;
            return (
              <tr key={e.expiry} data-testid="options-across-row" className="border-b border-strata-border/40">
                <td className="px-2 py-1 text-left text-strata-hi">
                  {shortDate(e.expiry, true)} <span className="text-strata-muted">· {expiryKind(e.expiry)}</span>
                </td>
                <td className={cell}>{daysLabel(e.days)}</td>
                <td className={cell}>{e.max_pain === null ? "—" : money(e.max_pain)}</td>
                <td className={cell}>
                  {gap === null || !price ? "—" : `${gap >= 0 ? "+" : "−"}${money(Math.abs(gap))} (${gap >= 0 ? "+" : "−"}${pct(Math.abs(gap) / price)})`}
                </td>
                <td className={cell}>{e.net_gex === null ? "—" : compactUsd(e.net_gex)}</td>
                <td className={cell}>{e.call_open_interest ? (e.put_open_interest / e.call_open_interest).toFixed(2) : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
