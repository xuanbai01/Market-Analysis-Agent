/**
 * Words for the trade journal (tastytrade PR D), written in code from the
 * server's figures: facts about past trades, nothing about what to do next.
 */
import { type Sentence, dateLabel } from "./options-text";
import type { JournalPosition, TradeJournal } from "./owner-schemas";
import { signedUsd, usd } from "./positions-text";

/** "open", "partly closed", "expired", "assigned", "closed in parts". */
export function endingLabel(position: JournalPosition): string {
  if (position.status === "open") return "open";
  if (position.status === "partly_closed") return "partly closed";
  if (position.ended_by === "mixed") return "closed in parts";
  return position.ended_by ?? "closed";
}

/** "same day", "1 day", "20 days". */
export function heldLabel(days: number | null): string {
  if (days === null) return "—";
  if (days === 0) return "same day";
  return `${days} day${days === 1 ? "" : "s"}`;
}

/** "the short put opened Nov 1": another position, named in a sentence. */
export function positionName(position: JournalPosition): string {
  const day = position.opened_on ?? position.opened_at?.slice(0, 10);
  const opened = day ? dateLabel(day) : "on an unknown date";
  return `the ${position.structure} opened ${opened}`;
}

/** "2026-11" → "Nov 2026". */
export function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
}

/** What closed, how often at a profit, how long held, and what it came to
 * (partial closes included, and said so); what closed without a computed
 * P&L (after a split) is counted apart. */
export function summarySentence(totals: TradeJournal["totals"]): Sentence {
  const plural = (n: number) => (n === 1 ? "" : "s");
  const parts: Sentence = [];
  if (totals.closed > 0) {
    const share = Math.round((totals.profitable / totals.closed) * 100);
    parts.push({ strong: `${totals.closed}` }, ` position${plural(totals.closed)} closed, `, { strong: `${totals.profitable}` });
    parts.push(" at a profit (", { strong: `${share}%` }, ")");
    if (totals.average_days !== null) parts.push(", held ", { strong: heldLabel(Math.round(totals.average_days)) }, " on average");
    parts.push(".");
  } else if (totals.partly > 0) {
    parts.push("Nothing closed in full yet.");
  }
  if (totals.closed > 0 || totals.partly > 0) {
    parts.push(" Realized: ", { strong: signedUsd(totals.realized) }, " after ", { strong: usd(totals.fees) }, " in fees");
    if (totals.partly > 0) {
      parts.push(totals.closed > 0 ? ", including " : ", from ", { strong: `${totals.partly}` }, ` partly closed position${plural(totals.partly)}`);
    }
    parts.push(".");
  }
  if (totals.unpriced > 0) {
    if (parts.length === 0) return [{ strong: `${totals.unpriced}` }, ` position${plural(totals.unpriced)} closed without a computed P&L.`];
    parts.push(" ", { strong: `${totals.unpriced}` }, " more closed without a computed P&L.");
  }
  return parts.length === 0 ? ["Nothing closed yet."] : parts;
}
