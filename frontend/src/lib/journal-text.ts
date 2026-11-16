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
  const opened = position.opened_at ? dateLabel(position.opened_at.slice(0, 10)) : "on an unknown date";
  return `the ${position.structure} opened ${opened}`;
}

/** "2026-11" → "Nov 2026". */
export function monthLabel(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleDateString("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
}

/** What closed, how often at a profit, how long held, and what it came to. */
export function summarySentence(totals: TradeJournal["totals"]): Sentence {
  if (totals.closed === 0) return ["Nothing closed yet."];
  const share = Math.round((totals.profitable / totals.closed) * 100);
  const parts: Sentence = [
    { strong: `${totals.closed}` },
    ` position${totals.closed === 1 ? "" : "s"} closed, `,
    { strong: `${totals.profitable}` },
    " at a profit (",
    { strong: `${share}%` },
    ")",
  ];
  if (totals.average_days !== null) parts.push(", held ", { strong: heldLabel(Math.round(totals.average_days)) }, " on average");
  parts.push(": ", { strong: signedUsd(totals.realized) }, " realized after ", { strong: usd(totals.fees) }, " in fees.");
  return parts;
}
