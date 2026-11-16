/**
 * The options page's words (ADR 0008): each chart's one-sentence takeaway,
 * expiry labels, and what the jargon means. Every number comes from the
 * report; the wording is fixed here, and nothing reads market direction
 * into a figure.
 *
 * A sentence is a list of segments: plain text, or a figure to set in bold.
 */
import type { ExpiryChain, ExpirySummary, OpenInterestTotal, Positioning, TopContract } from "./options-schemas";

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

/** Dollars in short form: "$48.9M", "−$17.0M", "$950K", "$2.40B". */
export function compactUsd(v: number): string {
  const sign = v < 0 ? "−" : "";
  const a = Math.abs(v);
  if (a >= 1e9) return `${sign}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${sign}$${(a / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `${sign}$${(a / 1e3).toFixed(0)}K`;
  return `${sign}$${a.toFixed(0)}`;
}

/** "$200", "$162.5". */
export function strikeLabel(k: number): string {
  return Number.isInteger(k) ? `$${k}` : `$${Number(k.toFixed(2))}`;
}

/** "Nov 16 $200 call". */
export function contractLabel(expiryIso: string, c: TopContract): string {
  return `${dateLabel(expiryIso)} ${strikeLabel(c.strike)} ${c.side}`;
}

/** "2.9% above", "1.2% below", "at": a level against the price. */
function versus(level: number, price: number): string {
  const gap = level / price - 1;
  if (Math.abs(gap) < 0.0005) return "at";
  return `${pct(Math.abs(gap))} ${gap > 0 ? "above" : "below"}`;
}

/** The expiry's open interest: totals, the ratio and the largest contract. */
export function positioningSentence(p: Positioning, expiryIso: string): Sentence | null {
  if (p.call_open_interest + p.put_open_interest === 0) return null;
  const parts: Sentence = [
    `${dateLabel(expiryIso)}: `,
    { strong: `${count(p.call_open_interest)} calls` },
    " and ",
    { strong: `${count(p.put_open_interest)} puts` },
    " open",
  ];
  if (p.put_call !== null) parts.push(" (put/call ", { strong: p.put_call.toFixed(2) }, ")");
  const top = p.top[0];
  if (top) parts.push("; the largest is the ", { strong: `${strikeLabel(top.strike)} ${top.side} (${count(top.open_interest)})` });
  parts.push(".");
  return parts;
}

/** Max pain against the price. */
export function maxPainSentence(p: Positioning, price: number | null): Sentence | null {
  if (p.max_pain === null) return null;
  const parts: Sentence = ["Max pain is ", { strong: usd(p.max_pain) }];
  if (price !== null && price > 0) parts.push(", ", { strong: versus(p.max_pain, price) }, " the price");
  parts.push(": the settle that would leave the most open contracts worthless.");
  return parts;
}

/** Net gamma exposure, and what its sign means under the dealer assumption. */
export function gammaSentence(p: Positioning): Sentence | null {
  if (p.call_open_interest + p.put_open_interest === 0) return null;
  const parts: Sentence = ["Net gamma exposure is ", { strong: `${compactUsd(p.net_gex)} per 1% move` }];
  if (Math.abs(p.net_gex) < 1) {
    parts.push(": calls and puts about offset.");
  } else {
    parts.push(
      p.net_gex > 0
        ? ": if dealers hold the other side as assumed, their hedging would damp moves"
        : ": if dealers hold the other side as assumed, their hedging would add to moves",
    );
    parts.push(p.gamma_flip !== null ? "; it changes sign near " : ".");
    if (p.gamma_flip !== null) parts.push({ strong: usd(p.gamma_flip) }, ".");
  }
  return parts;
}

/** Net delta exposure: which side's delta outweighs. */
export function deltaSentence(p: Positioning): Sentence | null {
  if (p.call_open_interest + p.put_open_interest === 0) return null;
  return [
    "Net delta exposure is ",
    { strong: `${compactUsd(p.net_dex)} per 1% move` },
    p.net_dex >= 0 ? ": calls' delta outweighs puts'." : ": puts' delta outweighs calls'.",
  ];
}

/** Max pain across the expiries read: its lowest and highest. */
export function acrossSentence(expiries: ExpirySummary[]): Sentence | null {
  const priced = expiries.filter((e): e is ExpirySummary & { max_pain: number } => e.max_pain !== null);
  if (priced.length < 2) return null;
  const low = priced.reduce((a, b) => (b.max_pain < a.max_pain ? b : a));
  const high = priced.reduce((a, b) => (b.max_pain > a.max_pain ? b : a));
  if (low.max_pain === high.max_pain) {
    return ["Max pain is ", { strong: usd(low.max_pain) }, ` at all ${priced.length} expiries with open interest.`];
  }
  return [
    "Max pain runs from ",
    { strong: usd(low.max_pain) },
    ` (${dateLabel(low.expiry)}) to `,
    { strong: usd(high.max_pain) },
    ` (${dateLabel(high.expiry)}) across the ${priced.length} expiries with open interest.`,
  ];
}

/** Contract counts in short form: "10.24M", "950K", "820". */
export function compactCount(v: number): string {
  if (v >= 999_500) return `${(v / 1e6).toFixed(2)}M`; // 999,600 is "1.00M", not "1000K"
  if (v >= 1e4) return `${(v / 1e3).toFixed(0)}K`;
  return count(v);
}

function change(now: number, then: number): string {
  const gap = now / then - 1;
  if (Math.abs(gap) < 0.0005) return "unchanged";
  return `${gap > 0 ? "up" : "down"} ${pct(Math.abs(gap))}`;
}

/** A session whose read covered every listed expiry. The night run stores a
 *  short read rather than lose the day, and beside whole reads it would look
 *  like open interest falling, so changes and lines use whole reads only. */
export const wholeRead = (h: OpenInterestTotal): boolean => h.expiries >= h.listed;

/** The latest whole-chain totals, and how they moved since the first whole read. */
export function openInterestHistorySentence(history: OpenInterestTotal[]): Sentence | null {
  const last = history[history.length - 1];
  if (!last) return null;
  const coverage = last.expiries < last.listed ? ` (${last.expiries} of ${last.listed} expiries read)` : "";
  const parts: Sentence = [
    `Across all ${last.listed} expiries${coverage}: `,
    { strong: `${compactCount(last.call)} calls` },
    " and ",
    { strong: `${compactCount(last.put)} puts` },
    ` open on ${dateLabel(last.date)}`,
  ];
  if (last.call > 0) parts.push(" (put/call ", { strong: (last.put / last.call).toFixed(2) }, ")");
  const first = history[0];
  const base = history.slice(0, -1).find(wholeRead);
  if (base && !wholeRead(last)) {
    parts.push(". The change is left out: this session's read was short.");
  } else if (base && base.call > 0 && base.put > 0) {
    parts.push(
      "; calls ",
      { strong: change(last.call, base.call) },
      " and puts ",
      { strong: change(last.put, base.put) },
      ` since ${dateLabel(base.date)}.`,
    );
  } else {
    parts.push(`. Recorded daily from ${dateLabel(first.date)}.`);
  }
  return parts;
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
  openInterest: "Contracts open at each strike, calls above the line and puts below; the dashed lines are the price and max pain.",
  topOpenInterest: "The contracts with the most open interest in this expiry, largest first.",
  maxPain:
    "The settle price, among the listed strikes, that would leave option holders the least. Widely watched; it describes where open interest sits, not where the price will go.",
  gamma:
    "Gamma exposure: how many dollars dealers' hedges would change for a 1% move in the stock, if dealers are long the calls and short the puts customers hold opposite them (the common assumption; real positions aren't public). Positive: their hedging damps moves; negative: it adds to them. Each bar is the net at a strike. The call and put walls are the strikes with the most call and put gamma exposure; the gamma flip is where the net changes sign as the price moves, each strike's IV held.",
  delta:
    "Delta exposure: the dollar change in the open options' own value for a 1% move in the stock, calls positive and puts negative, with no assumption about who holds them (a dealer's delta is the opposite of whatever side it holds). Some sites quote total dollar delta under this name, 100 times larger.",
  openInterestHistory:
    "Open contracts across every listed expiry, calls and puts, recorded after each session's close by our own daily run (from 2026-11-16; for a few tickers only, since it reads every expiry). One line per side; open interest is settled overnight, so each point is that session's.",
  tastytradeIvHistory:
    "From your tastytrade account, shown to you only and never stored: the stock's own IV each session from tastytrade's daily candles (from about 2016), and RV20, what the stock actually moved over the 20 sessions before, on the same scale. The sentence places today's IV among the past year's sessions; the table gives tastytrade's own rank and percentile, which it computes its own way.",
  acrossExpiries:
    "Each expiry the page reads: its max pain and how far that is from the price, its net gamma exposure, and its put/call open interest.",
} as const;
