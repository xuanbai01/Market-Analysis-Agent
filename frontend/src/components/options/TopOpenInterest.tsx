/**
 * TopOpenInterest — one expiry's largest open interest contracts, ranked:
 * a bar per contract in its side's colour, the count as text beside it.
 */
import type { TopContract } from "../../lib/options-schemas";
import { contractLabel } from "../../lib/options-text";
import { COLOR } from "./chart-kit";

export function TopOpenInterest({ expiry, top }: { expiry: string; top: TopContract[] }) {
  if (top.length === 0) return null;
  const most = Math.max(...top.map((c) => c.open_interest), 1);
  return (
    <ol data-testid="options-top-oi" className="space-y-1.5 font-mono text-[11px]">
      {top.map((c) => (
        <li key={`${c.side}-${c.strike}`} data-testid="options-top-oi-row" className="grid grid-cols-[9.5rem_1fr_4rem] items-center gap-2">
          <span className="truncate text-strata-dim">{contractLabel(expiry, c)}</span>
          <span className="h-2.5 rounded-sm bg-strata-raise" aria-hidden="true">
            <span
              className="block h-full rounded-sm"
              style={{ width: `${(c.open_interest / most) * 100}%`, background: c.side === "call" ? COLOR.call : COLOR.put }}
            />
          </span>
          <span className="text-right tabular-nums text-strata-fg">{c.open_interest.toLocaleString("en-US")}</span>
        </li>
      ))}
    </ol>
  );
}
