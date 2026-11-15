/**
 * The positions page's arithmetic (ADR 0009, amended): what a position is
 * worth now, at its first expiry and in a what-if; its Greeks in dollars;
 * what option prices imply about its chance of profit; how often the
 * stock's past moves would have left it in profit. Code computes every
 * figure from tastytrade's live quotes and our own chains; nothing here
 * ranks, forecasts or advises.
 *
 * Values are Black-76 on a forward drifting at ``carry`` (the rate less the
 * dividend yield, read off our chain), discounted at ``rate``, with each
 * leg's live IV. A leg with no IV can't be valued before expiry, and an
 * adjusted contract (a non-standard deliverable) isn't modelled at all:
 * then the figures that need it are null, never guessed.
 */
import { black76 } from "./options-pricing";
import { type Smile, probAbove } from "./options-strategy";
import type { PositionGroup, PositionLeg } from "./owner-schemas";

const DAY_MS = 24 * 3600 * 1000;
const YEAR_MS = 365 * DAY_MS;
// Options settle at the 4 pm New York close: 21:00 UTC in winter, 20:00 in
// summer. An hour off is noise for these figures.
const CLOSE_UTC = "T21:00:00Z";
const MIN_VOL = 0.01;
const ONE_PERCENT = 0.01;
// Price grid for breakevens: log-spaced over a wide range around the spot.
const GRID_POINTS = 800;
const GRID_LOW = 0.2;
const GRID_HIGH = 4;
// Fewer past windows than this says nothing.
const MIN_WINDOWS = 20;

export interface Market {
  /** The underlying's live price (tastytrade's mark). */
  spot: number;
  /** Annual rate for discounting. */
  rate: number;
  /** Annual drift of the forward: the rate less the dividend yield. */
  carry: number;
  now: Date;
}

/** A what-if: the stock moved by ``move`` (0.05 = up 5%), IV shifted by
 * ``ivShift`` (0.1 = 10 points higher), ``days`` calendar days on. */
export interface Scenario {
  move: number;
  ivShift: number;
  days: number;
}

export const NO_CHANGE: Scenario = { move: 0, ivShift: 0, days: 0 };

const size = (leg: PositionLeg) => leg.quantity * leg.multiplier;
const isOption = (leg: PositionLeg) => leg.kind !== "stock";

export function expiryClose(expiry: string): Date {
  return new Date(`${expiry}${CLOSE_UTC}`);
}

export function yearsTo(expiry: string, at: Date): number {
  return Math.max(0, (expiryClose(expiry).getTime() - at.getTime()) / YEAR_MS);
}

/** Every leg can be valued: none is an adjusted contract. */
export function modelled(group: PositionGroup): boolean {
  return !group.legs.some((leg) => leg.adjusted);
}

function intrinsic(leg: PositionLeg, price: number): number {
  const strike = leg.strike ?? 0;
  return leg.kind === "call" ? Math.max(price - strike, 0) : Math.max(strike - price, 0);
}

/** One leg's value per share with the stock at ``price`` at ``at``; null
 * when it needs an IV tastytrade didn't send. */
export function legValue(leg: PositionLeg, price: number, at: Date, ivShift: number, market: Market): number | null {
  if (leg.kind === "stock") return price;
  if (leg.expiry === null || leg.strike === null) return null;
  const years = yearsTo(leg.expiry, at);
  if (years <= 0) return intrinsic(leg, price);
  const iv = leg.quote?.iv;
  if (iv === null || iv === undefined) return null;
  const forward = price * Math.exp(market.carry * years);
  return black76(forward, leg.strike, years, Math.max(iv + ivShift, MIN_VOL), Math.exp(-market.rate * years), leg.kind === "call");
}

/** What the group is worth with the stock at ``price`` at ``at``. */
export function valueAt(group: PositionGroup, price: number, at: Date, ivShift: number, market: Market): number | null {
  if (!modelled(group)) return null;
  let total = 0;
  for (const leg of group.legs) {
    const value = legValue(leg, price, at, ivShift, market);
    if (value === null) return null;
    total += size(leg) * value;
  }
  return total;
}

/** What opening it cost: paid is positive, taken in negative. */
export function costBasis(group: PositionGroup): number | null {
  let total = 0;
  for (const leg of group.legs) {
    if (leg.average_open === null) return null;
    total += size(leg) * leg.average_open;
  }
  return total;
}

/** What it's worth at tastytrade's marks now. */
export function markValue(group: PositionGroup): number | null {
  let total = 0;
  for (const leg of group.legs) {
    const mark = (isOption(leg) ? leg.quote?.mark : (leg.quote?.mark ?? group.quote?.mark)) ?? null;
    if (mark === null) return null;
    total += size(leg) * mark;
  }
  return total;
}

export function firstExpiry(group: PositionGroup): string | null {
  return group.expiries[0] ?? null;
}

/** P&L at the first expiry with the stock at ``price`` (legs expiring
 * later are valued then); with no options, P&L now. */
export function pnlAtExpiry(group: PositionGroup, price: number, market: Market): number | null {
  const first = firstExpiry(group);
  const value = valueAt(group, price, first ? expiryClose(first) : market.now, 0, market);
  const cost = costBasis(group);
  return value === null || cost === null ? null : value - cost;
}

/** P&L in a what-if, from the live spot. */
export function pnlInScenario(group: PositionGroup, scenario: Scenario, market: Market): number | null {
  const at = new Date(market.now.getTime() + scenario.days * DAY_MS);
  const value = valueAt(group, market.spot * (1 + scenario.move), at, scenario.ivShift, market);
  const cost = costBasis(group);
  return value === null || cost === null ? null : value - cost;
}

export interface Greeks {
  /** Shares the position moves like. */
  deltaShares: number | null;
  /** P&L for a 1% move in the stock, from delta. */
  deltaDollars: number | null;
  /** How many shares delta changes by for a 1% rise. */
  gammaShares: number | null;
  /** P&L for a day passing, nothing else changing. */
  thetaDay: number | null;
  /** P&L for IV one point higher. */
  vegaPoint: number | null;
}

function total(group: PositionGroup, pick: (leg: PositionLeg) => number | null): number | null {
  let sum = 0;
  for (const leg of group.legs) {
    const v = pick(leg);
    if (v === null) return null;
    sum += size(leg) * v;
  }
  return sum;
}

/** The group's Greeks from tastytrade's per-share ones (a share's delta is 1). */
export function greeks(group: PositionGroup, spot: number): Greeks {
  const option = (name: "delta" | "gamma" | "theta" | "vega", stock: number) => (leg: PositionLeg) =>
    isOption(leg) ? (leg.quote?.[name] ?? null) : stock;
  const deltaShares = total(group, option("delta", 1));
  const gamma = total(group, option("gamma", 0));
  return {
    deltaShares,
    deltaDollars: deltaShares === null ? null : deltaShares * spot * ONE_PERCENT,
    gammaShares: gamma === null ? null : gamma * spot * ONE_PERCENT,
    thetaDay: total(group, option("theta", 0)),
    vegaPoint: total(group, option("vega", 0)),
  };
}

function grid(spot: number): number[] {
  const lo = Math.log(spot * GRID_LOW);
  const hi = Math.log(spot * GRID_HIGH);
  return Array.from({ length: GRID_POINTS + 1 }, (_, i) => Math.exp(lo + ((hi - lo) * i) / GRID_POINTS));
}

/** Where the P&L at the first expiry crosses zero, between a fifth of the
 * spot and four times it. */
export function breakevens(group: PositionGroup, market: Market): number[] {
  const xs = grid(market.spot);
  const ys = xs.map((x) => pnlAtExpiry(group, x, market));
  const found: number[] = [];
  for (let i = 0; i + 1 < xs.length; i++) {
    const [a, b] = [ys[i], ys[i + 1]];
    if (a === null || b === null) return [];
    if (a === 0) found.push(xs[i]);
    else if (a * b < 0) found.push(xs[i] + ((xs[i + 1] - xs[i]) * a) / (a - b));
  }
  return found;
}

/** The risk-neutral chance the position is in profit at its expiry, from
 * that expiry's smile: what option prices imply, not a forecast. Null for
 * a spread across expiries (it would need the joint distribution) or a
 * position it can't value. */
export function profitChance(group: PositionGroup, smile: Smile, market: Market): number | null {
  if (group.expiries.length !== 1 || costBasis(group) === null || !modelled(group)) return null;
  const edges = [0, ...breakevens(group, market), Infinity];
  const above = (k: number) => (k === 0 ? 1 : k === Infinity ? 0 : probAbove(smile, k));
  let chance = 0;
  for (let i = 0; i + 1 < edges.length; i++) {
    const [a, b] = [edges[i], edges[i + 1]];
    const probe = b === Infinity ? a * 1.5 + 1 : (a + b) / 2;
    const pnl = pnlAtExpiry(group, probe, market);
    if (pnl !== null && pnl > 0) chance += above(a) - above(b);
  }
  return chance;
}

/** Trading sessions from ``now`` to the expiry's close (weekdays; holidays
 * aside). */
export function sessionsUntil(expiry: string, now: Date): number {
  const end = expiryClose(expiry).getTime();
  let count = 0;
  for (let t = now.getTime() + DAY_MS; t <= end + DAY_MS / 2; t += DAY_MS) {
    const day = new Date(t).getUTCDay();
    if (day !== 0 && day !== 6) count++;
  }
  return count;
}

/** How often, over the closes given (oldest first), the stock's move across
 * ``sessions`` sessions would have left the position in profit at its
 * first expiry: past moves, not a forecast. Null with too few windows. */
export function historicalShare(
  group: PositionGroup,
  closes: number[],
  sessions: number,
  market: Market,
): { share: number; windows: number } | null {
  if (sessions < 1) return null;
  let wins = 0;
  let windows = 0;
  for (let i = 0; i + sessions < closes.length; i++) {
    if (!(closes[i] > 0)) continue;
    const pnl = pnlAtExpiry(group, market.spot * (closes[i + sessions] / closes[i]), market);
    if (pnl === null) return null;
    windows++;
    if (pnl > 0) wins++;
  }
  return windows < MIN_WINDOWS ? null : { share: wins / windows, windows };
}
