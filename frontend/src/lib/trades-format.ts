/** Formatting for the owner's trades: the transactions table and the journal. */
import type { OwnerTrade } from "./owner-schemas";

/** When a fill happened, in the reader's time; its date when there's no time. */
export function tradeTime(trade: OwnerTrade): string {
  if (trade.executed_at) return new Date(trade.executed_at).toLocaleString();
  return trade.date ?? "—";
}

export const num = (v: number | null, digits = 2) => (v === null ? "—" : v.toFixed(digits));

/** To the cent, like the fees beside it: two nets a few cents apart don't read alike. */
export const cents = (v: number) => {
  const sign = v > 0.004 ? "+" : v < -0.004 ? "−" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
};

/** As many decimals as it has, up to 4: a fractional share isn't rounded to a whole one. */
export const quantity = (v: number | null) => (v === null ? "—" : v.toLocaleString("en-US", { maximumFractionDigits: 4 }));
