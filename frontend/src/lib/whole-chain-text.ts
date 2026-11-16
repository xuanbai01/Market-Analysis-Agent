/**
 * Words for the options page's whole-chain panel (tastytrade, the owner's
 * alone): what the read covers, the chain's open interest and walls, and
 * what was left out. Facts only: nothing says what to do.
 */
import { type Sentence, dateLabel, strikeLabel } from "./options-text";
import type { WholeChain } from "./owner-schemas";

const count = (v: number) => v.toLocaleString("en-US");
const pct = (v: number) => `${Math.round(v * 100)}%`;

export function wholeChainSentence(w: WholeChain): Sentence | null {
  const p = w.positioning;
  if (w.expiries.length === 0 || p.call_open_interest + p.put_open_interest === 0) return null;
  const last = w.expiries[w.expiries.length - 1].expiry;
  const parts: Sentence = [
    "Every expiry to ",
    { strong: dateLabel(last) },
    ` (${w.expiries.length === 1 ? "1 expiry" : `${w.expiries.length} expiries`}, strikes within ${pct(w.strike_range)} of the price): `,
    { strong: `${count(p.call_open_interest)} calls` },
    " and ",
    { strong: `${count(p.put_open_interest)} puts` },
    " open",
  ];
  if (p.put_call !== null) parts.push(" (put/call ", { strong: p.put_call.toFixed(2) }, ")");
  if (p.call_wall !== null || p.put_wall !== null) {
    parts.push("; the chain's");
    if (p.call_wall !== null) parts.push(" call wall is ", { strong: strikeLabel(p.call_wall) });
    if (p.call_wall !== null && p.put_wall !== null) parts.push(" and its");
    if (p.put_wall !== null) parts.push(" put wall ", { strong: strikeLabel(p.put_wall) });
  }
  parts.push(".");
  return parts;
}

/** What the read couldn't cover, or nothing. */
export function wholeChainNotes(w: WholeChain): string[] {
  const notes: string[] = [];
  if (w.left_out.length > 0) {
    notes.push(`No usable quotes for ${w.left_out.map((d) => dateLabel(d)).join(", ")}: left out.`);
  }
  if (w.capped) notes.push("More contracts than one read takes: the farthest expiries are left out.");
  if (w.options_quoted < w.options_read) {
    notes.push(`${count(w.options_read - w.options_quoted)} of ${count(w.options_read)} contracts sent no quote or open interest.`);
  }
  return notes;
}
