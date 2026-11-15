/**
 * The options page's words (ADR 0008): each chart's one-sentence takeaway,
 * expiry labels, and what the jargon means. Every number comes from the
 * report; the wording is fixed here, and nothing reads market direction
 * into a figure.
 *
 * A sentence is a list of segments: plain text, or a figure to set in bold.
 */
import type { ExpiryChain, ExpirySummary } from "./options-schemas";

export type Segment = string | { strong: string };
export type Sentence = Segment[];

const pct = (v: number, digits = 1) => `${(v * 100).toFixed(digits)}%`;
const usd = (v: number) => `$${v.toFixed(2)}`;
const pts = (v: number) => `${Math.abs(v * 100).toFixed(1)} points`;

/** "2026-12-11" → "Dec 11"; with a year, "Dec 11, 2026". */
export function dateLabel(iso: string, withYear = false): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
    ...(withYear ? { year: "numeric" } : {}),
  });
}

function easter(year: number): Date {
  // Anonymous Gregorian algorithm.
  const a = year % 19;
  const b = Math.floor(year / 100);
  const c = year % 100;
  const d = Math.floor(b / 4);
  const e = b % 4;
  const f = Math.floor((b + 8) / 25);
  const g = Math.floor((b - f + 1) / 3);
  const h = (19 * a + b - d - g + 15) % 30;
  const i = Math.floor(c / 4);
  const k = c % 4;
  const l = (32 + 2 * e + 2 * i - h - k) % 7;
  const m = Math.floor((a + 11 * h + 22 * l) / 451);
  const month = Math.floor((h + l - 7 * m + 114) / 31);
  const day = ((h + l - 7 * m + 114) % 31) + 1;
  return new Date(Date.UTC(year, month - 1, day));
}

/** NYSE holidays that can fall on a month's third Friday (the 15th to the
 * 21st): Good Friday, and Juneteenth on June 19 or, when that's a
 * Saturday, observed on Friday the 18th. The others never land there. */
function fridayHoliday(date: Date): boolean {
  const year = date.getUTCFullYear();
  const goodFriday = new Date(easter(year).getTime() - 2 * 86_400_000);
  const sameDay = (x: Date) => x.getUTCMonth() === date.getUTCMonth() && x.getUTCDate() === date.getUTCDate();
  if (sameDay(goodFriday)) return true;
  if (year < 2022 || date.getUTCMonth() !== 5) return false;
  const juneteenth = new Date(Date.UTC(year, 5, 19));
  const observed = juneteenth.getUTCDay() === 6 ? 18 : juneteenth.getUTCDay() === 0 ? 20 : 19;
  return date.getUTCDate() === observed;
}

function utc(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

/** "monthly" for the standard monthly expiry (the third Friday, or the
 * Thursday before when that Friday is a holiday), else "weekly". */
export function expiryKind(iso: string): "monthly" | "weekly" {
  const date = utc(iso);
  const dom = date.getUTCDate();
  const dow = date.getUTCDay();
  if (dow === 5 && dom >= 15 && dom <= 21) return fridayHoliday(date) ? "weekly" : "monthly";
  if (dow === 4 && dom >= 14 && dom <= 20) {
    const friday = new Date(date.getTime() + 86_400_000);
    return fridayHoliday(friday) ? "monthly" : "weekly";
  }
  return "weekly";
}

export function daysLabel(days: number): string {
  const n = Math.max(0, Math.round(days));
  return n === 1 ? "1 day" : `${n} days`;
}

/** Calendar days from the quote's date to an expiry's date. */
export function daysUntil(quotedAtIso: string, expiryIso: string): number {
  return Math.round((Date.parse(expiryIso.slice(0, 10)) - Date.parse(quotedAtIso.slice(0, 10))) / 86_400_000);
}

/** "Nov 20, 2026 · 5 days · monthly" */
export function expiryLabel(expiryIso: string, days: number): string {
  return `${dateLabel(expiryIso, true)} · ${daysLabel(days)} · ${expiryKind(expiryIso)}`;
}

/** The expiry nearest ``target`` days among those a week or more out (any, if none is). */
function nearest(expiries: ExpirySummary[], target: number): ExpirySummary | undefined {
  const eligible = expiries.filter((e) => e.days >= 7);
  const pool = eligible.length > 0 ? eligible : expiries;
  return pool.reduce<ExpirySummary | undefined>(
    (best, e) => (best === undefined || Math.abs(e.days - target) < Math.abs(best.days - target) ? e : best),
    undefined,
  );
}

/** The cone: the expected move to the expiry nearest 30 days. */
export function coneSentence(expiries: ExpirySummary[], spot: number): Sentence | null {
  const e = nearest(expiries, 30);
  if (!e) return null;
  return [
    "Options price a ",
    { strong: `±${pct(e.expected_move)} (${usd(spot * e.expected_move)})` },
    " move by ",
    { strong: dateLabel(e.expiry) },
    ", one standard deviation: option prices put about a two-in-three chance on the price ending inside it.",
  ];
}

/** The term structure: the nearest expiry's at-the-money IV against the
 * farthest's, the same two ends the chart draws. */
export function termSentence(expiries: ExpirySummary[]): Sentence | null {
  const sorted = [...expiries].sort((a, b) => a.days - b.days);
  const front = sorted[0];
  const back = sorted[sorted.length - 1];
  if (!front || !back || front === back) return null;
  const gap = back.atm_iv - front.atm_iv;
  const shape =
    Math.abs(gap) < 0.005
      ? "about flat: near and far expiries price similar movement."
      : gap < 0
        ? "sloping down: near expiries price more movement than far ones."
        : "sloping up: far expiries price more movement than near ones.";
  return [
    "At-the-money IV runs from ",
    { strong: pct(front.atm_iv) },
    ` at ${daysLabel(front.days)} to `,
    { strong: pct(back.atm_iv) },
    ` at ${daysLabel(back.days)}, `,
    shape,
  ];
}

/** The smile: the 25-delta skew of the expiry nearest 30 days. */
export function smileSentence(skew25: number | null): Sentence | null {
  if (skew25 === null) return null;
  if (Math.abs(skew25) < 0.0005) return ["25Δ puts and calls are priced at about the same IV."];
  return [
    "25Δ puts are priced ",
    { strong: pts(skew25) },
    skew25 > 0 ? " above 25Δ calls: downside protection costs more." : " below 25Δ calls: upside calls cost more.",
  ];
}

const count = (v: number) => v.toLocaleString("en-US");

/** Open interest near the money: the largest call and put strikes shown. */
export function openInterestSentence(chain: ExpiryChain): Sentence | null {
  if (chain.open_interest.length === 0) return null;
  const topCall = chain.open_interest.reduce((a, b) => (b.call > a.call ? b : a));
  const topPut = chain.open_interest.reduce((a, b) => (b.put > a.put ? b : a));
  const parts: Sentence = ["Most open near the money: "];
  if (topCall.call > 0) parts.push({ strong: `${usd(topCall.strike)} calls (${count(topCall.call)})` });
  if (topCall.call > 0 && topPut.put > 0) parts.push(" and ");
  if (topPut.put > 0) parts.push({ strong: `${usd(topPut.strike)} puts (${count(topPut.put)})` });
  parts.push(".");
  return topCall.call > 0 || topPut.put > 0 ? parts : null;
}

/** What each figure on the page means, for the ⓘ beside it. */
export const GLOSSARY = {
  spot: "The underlying's price the option quotes go with: the last close Yahoo reports outside market hours, the 15-minute-delayed price during them. Feeds can differ by a few cents on a close.",
  iv30: "Implied volatility 30 days out: the yearly move option prices imply, interpolated between the expiries around 30 days. RV20 is what the stock actually moved over the last 20 sessions, on the same scale.",
  ivHistory: "Where today's IV30 sits among our own daily IV30 records: the percentile needs 63 sessions, which we started collecting on 2026-11-13.",
  expectedMove: "One standard deviation of the price at that expiry, from at-the-money IV: the price ends inside this range about two times in three.",
  skew: "Put IV minus call IV at 25 delta, the expiry nearest 30 days. Positive: downside protection costs more than upside.",
  putCall: "Put open interest divided by call open interest, over the expiries read. Above 1, more puts are open than calls.",
  cone: "The range the price stays inside about two times in three, by expiry, widening with time; dots are the listed expiries.",
  term: "At-the-money implied volatility by days to expiry. An expiry holding the next earnings report is hollow: the report adds a jump to its IV.",
  earnings: "The move options price for the next report, from the expiries around it, beside the stock's actual moves after past reports.",
  smile: "Implied volatility by strike for one expiry, from the out-of-the-money side: puts below the forward, calls above.",
  openInterest: "Contracts open at each strike, calls above the line and puts below; the dashed line is the price.",
} as const;
