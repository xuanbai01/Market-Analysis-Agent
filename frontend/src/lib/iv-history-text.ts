/**
 * Words and figures for the options page's IV history panel (tastytrade,
 * the owner's alone): a sentence placing today's IV among the past year's
 * sessions and against realized volatility, tastytrade's own figures for
 * the table, and the sessions each range draws. Facts only: nothing says
 * what to do.
 */
import { type Sentence, dateLabel } from "./options-text";
import type { IvHistory, IvPoint } from "./owner-schemas";

export type IvRange = "1Y" | "3Y" | "All";
export const IV_RANGES: IvRange[] = ["1Y", "3Y", "All"];
const SESSIONS: Record<IvRange, number | null> = { "1Y": 252, "3Y": 756, All: null };
const YEAR = 252;

const pct = (v: number, digits = 1) => `${(v * 100).toFixed(digits)}%`;
const maybePct = (v: number | null, digits = 1) => (v === null ? "—" : pct(v, digits));

/** The last ``range`` of sessions. */
export function inRange(points: IvPoint[], range: IvRange): IvPoint[] {
  const n = SESSIONS[range];
  return n === null ? points : points.slice(-n);
}

/** A series' latest value. */
export function latest(points: IvPoint[], key: "iv" | "rv20"): number | null {
  for (let i = points.length - 1; i >= 0; i--) {
    const v = points[i][key];
    if (v !== null) return v;
  }
  return null;
}

export function ivHistorySentence(history: IvHistory): Sentence | null {
  const iv = latest(history.points, "iv");
  if (iv === null) return null;
  const { year } = history;
  const parts: Sentence = ["IV is ", { strong: pct(iv) }];
  if (year.iv_percentile !== null && year.sessions > 1) {
    const span = year.sessions >= YEAR ? "the past year's sessions" : `the ${year.sessions} sessions with an IV`;
    parts.push(", higher than on ", { strong: `${Math.round(year.iv_percentile * 100)}%` }, ` of ${span}`);
    if (year.iv_low !== null && year.iv_high !== null) {
      parts.push(" (from ", { strong: pct(year.iv_low) }, " to ", { strong: pct(year.iv_high) }, ")");
    }
  }
  parts.push(".");
  const rv = latest(history.points, "rv20");
  if (rv !== null) {
    const gap = iv - rv;
    parts.push(
      " Realized volatility over the last 20 sessions is ",
      { strong: pct(rv) },
      ", ",
      { strong: `${Math.abs(gap * 100).toFixed(1)} points` },
      gap >= 0 ? " below IV." : " above IV.",
    );
  }
  return parts;
}

/** tastytrade's own figures, which it computes its own way. */
export function ivHistoryStats(history: IvHistory): { label: string; value: string }[] {
  const m = history.metrics;
  return [
    { label: "IV index (tastytrade)", value: maybePct(m.iv_index) },
    { label: "IV rank (tastytrade)", value: maybePct(m.iv_rank, 0) },
    { label: "IV percentile (tastytrade)", value: maybePct(m.iv_percentile, 0) },
    { label: "IV30 (tastytrade)", value: maybePct(m.iv30) },
    { label: "HV30 / HV60 / HV90", value: `${maybePct(m.hv30)} / ${maybePct(m.hv60)} / ${maybePct(m.hv90)}` },
    { label: "IV since", value: history.iv_since ? dateLabel(history.iv_since, true) : "—" },
  ];
}
