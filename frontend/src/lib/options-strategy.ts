/**
 * The strategy builder's arithmetic (ADR 0008, PR4): payoff at expiry,
 * breakevens, the most a position makes and loses, and the risk-neutral
 * probability of profit from the expiry's smile. Templates only: nothing
 * here ranks or suggests a trade.
 *
 * Held to the Python figures in options-strategy.golden.json (normal CDF
 * and the chance of ending above a strike to 1e-6, the probability of
 * profit to 1e-4), which tests/test_options_strategy_golden.py computes
 * from app/services/options_math by a different route. Probabilities use
 * the smile averaged over half a one-sigma move either side.
 *
 * Imported only by the lazy options page.
 */
import type { ChainRow, ExpiryChain } from "./options-schemas";

export const CONTRACT_SIZE = 100;

export type OptionKind = "call" | "put";
/** 1 bought, −1 sold. */
export type Side = 1 | -1;
export interface Leg {
  kind: OptionKind;
  side: Side;
  strike: number;
}
export interface PricedLeg extends Leg {
  /** Per share. */
  premium: number;
}
export interface Quote {
  bid: number;
  ask: number;
}
/** Mid: halfway between bid and ask. Natural: buy at the ask, sell at the bid. */
export type Basis = "mid" | "natural";

/** An expiry's smile: IV at points of ln(K/F), ascending. */
export interface Smile {
  forward: number;
  years: number;
  points: [number, number][];
}

// ── Normal distribution ─────────────────────────────────────────────

const SQRT_2PI = Math.sqrt(2 * Math.PI);

/** Abramowitz & Stegun 7.1.26 for erf: absolute error under 1.5e-7. */
export function normCdf(x: number): number {
  const z = Math.abs(x) / Math.SQRT2;
  const t = 1 / (1 + 0.3275911 * z);
  const poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))));
  const erf = 1 - poly * Math.exp(-z * z);
  return x >= 0 ? (1 + erf) / 2 : (1 - erf) / 2;
}

function normPdf(x: number): number {
  return Math.exp((-x * x) / 2) / SQRT_2PI;
}

// ── Prices ──────────────────────────────────────────────────────────

/** A leg's price per share, or null where the market doesn't give one.
 * Mid needs both a bid and an offer; natural buys at the offer and sells
 * at the bid, so with no offer there's nothing to buy and with no bid
 * nobody to sell to. */
export function premium(q: Quote, side: Side, basis: Basis): number | null {
  if (basis === "mid") return q.bid > 0 && q.ask > 0 ? (q.bid + q.ask) / 2 : null;
  const price = side === 1 ? q.ask : q.bid;
  return price > 0 ? price : null;
}

export function quoteFor(rows: ChainRow[], leg: Leg): Quote | null {
  const row = rows.find((r) => r.strike === leg.strike);
  if (!row) return null;
  return leg.kind === "call" ? { bid: row.call_bid, ask: row.call_ask } : { bid: row.put_bid, ask: row.put_ask };
}

// ── Payoff at expiry (per share, net of what the legs cost) ────────

const cost = (legs: PricedLeg[]) => legs.reduce((sum, l) => sum + l.side * l.premium, 0);

export function payoff(legs: PricedLeg[], price: number): number {
  const value = legs.reduce(
    (sum, l) => sum + l.side * (l.kind === "call" ? Math.max(price - l.strike, 0) : Math.max(l.strike - price, 0)),
    0,
  );
  return value - cost(legs);
}

/** Price points where the payoff bends (0 and each strike), ascending. */
function knots(legs: PricedLeg[]): number[] {
  return [0, ...new Set(legs.map((l) => l.strike))].sort((a, b) => a - b);
}

/** The payoff's slope above the highest strike: +1 for each call bought. */
function slopeAbove(legs: PricedLeg[]): number {
  return legs.reduce((sum, l) => sum + (l.kind === "call" ? l.side : 0), 0);
}

const EPS = 1e-9;

/** Prices at expiry where the position turns from loss to profit or back
 * (profit means a payoff above zero). */
export function breakevens(legs: PricedLeg[]): number[] {
  const xs = knots(legs);
  const found: number[] = [];
  const add = (x: number) => {
    if (!found.some((f) => Math.abs(f - x) < EPS)) found.push(x);
  };
  for (let i = 0; i + 1 < xs.length; i++) {
    const [a, b] = [xs[i], xs[i + 1]];
    const [pa, pb] = [payoff(legs, a), payoff(legs, b)];
    if (pa > 0 !== pb > 0) add(a + ((b - a) * -pa) / (pb - pa));
  }
  const last = xs[xs.length - 1];
  const pLast = payoff(legs, last);
  const slope = slopeAbove(legs);
  if ((pLast > 0 && slope < 0) || (pLast <= 0 && slope > 0)) add(last - pLast / slope);
  return found.sort((a, b) => a - b);
}

/** The most the position makes and loses at expiry, per share; null where
 * it has no bound (a call bought has no cap, a call sold no floor). */
export function extremes(legs: PricedLeg[]): { maxProfit: number | null; maxLoss: number | null } {
  const values = knots(legs).map((x) => payoff(legs, x));
  const slope = slopeAbove(legs);
  return {
    maxProfit: slope > 0 ? null : Math.max(...values),
    maxLoss: slope < 0 ? null : Math.min(...values),
  };
}

// ── Risk-neutral probabilities from the smile ───────────────────────

/** IV at x = ln(K/F): linear between points, flat beyond them. */
function volAt(points: [number, number][], x: number): number {
  const n = points.length;
  if (x <= points[0][0]) return points[0][1];
  if (x >= points[n - 1][0]) return points[n - 1][1];
  let i = 0;
  while (points[i + 1][0] < x) i++;
  const [x0, v0] = points[i];
  const [x1, v1] = points[i + 1];
  return v0 + ((v1 - v0) * (x - x0)) / (x1 - x0);
}

/** ∫ σ from the first point to x (negative to its left), for ``volAt``'s σ. */
function area(points: [number, number][], x: number): number {
  const [x0, v0] = points[0];
  if (x <= x0) return v0 * (x - x0);
  let total = 0;
  for (let i = 0; i + 1 < points.length; i++) {
    const [a, va] = points[i];
    const [b, vb] = points[i + 1];
    const end = Math.min(x, b);
    total += ((va + va + ((vb - va) * (end - a)) / (b - a)) / 2) * (end - a);
    if (x <= b) return total;
  }
  const [xn, vn] = points[points.length - 1];
  return total + vn * (x - xn);
}

/** The half-width, in ln(K/F), the smile is averaged over for
 * probabilities: half a one-sigma move, from 2% to 15%. Taking the slope
 * of the raw piecewise smile let one noisy quote spike the density. */
function halfWidth(smile: Smile): number {
  return Math.min(0.15, Math.max(0.02, 0.5 * volAt(smile.points, 0) * Math.sqrt(smile.years)));
}

/** The averaged smile at x and its slope dσ/d ln K. */
function smoothedAt(smile: Smile, x: number): { vol: number; slope: number } {
  const h = halfWidth(smile);
  const { points } = smile;
  return {
    vol: (area(points, x + h) - area(points, x - h)) / (2 * h),
    slope: (volAt(points, x + h) - volAt(points, x - h)) / (2 * h),
  };
}

/** The risk-neutral chance the stock ends above ``strike``: −dC/dK along
 * the averaged smile, N(d2) − φ(d2)·√T·dσ/d ln K. The skew term is why a
 * put-heavy smile makes a fall likelier than a flat vol would. */
export function probAbove(smile: Smile, strike: number): number {
  if (strike <= 0) return 1;
  const { forward, years } = smile;
  const { vol, slope } = smoothedAt(smile, Math.log(strike / forward));
  if (vol <= 0 || years <= 0) return forward > strike ? 1 : 0; // nothing left to vary
  const root = Math.sqrt(years);
  const d2 = (Math.log(forward / strike) - (vol * vol * years) / 2) / (vol * root);
  return Math.min(1, Math.max(0, normCdf(d2) - normPdf(d2) * root * slope));
}

/** The risk-neutral chance the payoff at expiry is above zero: the
 * probability mass between breakevens where the position profits. */
export function probProfit(legs: PricedLeg[], smile: Smile): number {
  const edges = [0, ...breakevens(legs), Infinity];
  let prob = 0;
  for (let i = 0; i + 1 < edges.length; i++) {
    const [a, b] = [edges[i], edges[i + 1]];
    const probe = b === Infinity ? a * 2 + 1 : (a + b) / 2;
    if (payoff(legs, probe) > 0) {
      // Never a negative mass, whatever the smile's shape.
      prob += Math.max(0, (a === 0 ? 1 : probAbove(smile, a)) - (b === Infinity ? 0 : probAbove(smile, b)));
    }
  }
  return Math.min(1, Math.max(0, prob));
}

/** The expiry's smile, one point per moneyness (two at one strike are
 * averaged), or null with none. */
export function smileOf(chain: ExpiryChain): Smile | null {
  if (chain.smile.length === 0 || chain.days <= 0) return null;
  const byX = new Map<number, number[]>();
  for (const p of chain.smile) byX.set(p.log_moneyness, [...(byX.get(p.log_moneyness) ?? []), p.iv]);
  const points = [...byX.entries()]
    .map(([x, ivs]) => [x, ivs.reduce((a, b) => a + b, 0) / ivs.length] as [number, number])
    .sort((a, b) => a[0] - b[0]);
  return { forward: chain.forward, years: chain.days / 365, points };
}

/** The expiry's one-sigma move as a fraction (σ√T): the chain's ATM IV,
 * else the smile's IV at the forward; null with neither. */
export function oneSigma(chain: ExpiryChain): number | null {
  const smile = smileOf(chain);
  const vol = chain.atm_iv ?? (smile ? volAt(smile.points, 0) : null);
  return vol === null || chain.days <= 0 ? null : vol * Math.sqrt(chain.days / 365);
}

// ── One position, analysed ─────────────────────────────────────────

export interface Analysis {
  /** Per share: positive is a debit paid, negative a credit taken in. */
  cost: number;
  breakevens: number[];
  maxProfit: number | null;
  maxLoss: number | null;
  /** Risk-neutral, at expiry; null without a smile. */
  pop: number | null;
  priced: PricedLeg[];
}

/** Null when any leg can't be priced on this basis. */
export function analyse(legs: Leg[], rows: ChainRow[], basis: Basis, smile: Smile | null): Analysis | null {
  const priced: PricedLeg[] = [];
  for (const leg of legs) {
    const q = quoteFor(rows, leg);
    const p = q && premium(q, leg.side, basis);
    if (p === null || p === undefined) return null;
    priced.push({ ...leg, premium: p });
  }
  return {
    cost: cost(priced),
    breakevens: breakevens(priced),
    ...extremes(priced),
    pop: smile ? probProfit(priced, smile) : null,
    priced,
  };
}

// ── Templates ──────────────────────────────────────────────────────

export const TEMPLATES = {
  long_call: "Long call",
  long_put: "Long put",
  bull_call: "Bull call spread",
  bear_put: "Bear put spread",
  bull_put: "Bull put spread",
  bear_call: "Bear call spread",
  iron_condor: "Iron condor",
} as const;
export type Template = keyof typeof TEMPLATES;

/** Strikes a leg can trade at, ascending: an offer to buy from, a bid to
 * sell to. */
function quotedStrikes(rows: ChainRow[], kind: OptionKind, side: Side): number[] {
  return rows
    .filter((r) => {
      const [bid, ask] = kind === "call" ? [r.call_bid, r.call_ask] : [r.put_bid, r.put_ask];
      return (side === 1 ? ask : bid) > 0;
    })
    .map((r) => r.strike)
    .sort((a, b) => a - b);
}

function nearest(strikes: number[], target: number): number | null {
  return strikes.reduce<number | null>((best, k) => (best === null || Math.abs(k - target) < Math.abs(best - target) ? k : best), null);
}

/**
 * A template's legs at strikes picked by a fixed rule from the forward and
 * the expiry's one-sigma move (σ√T): long legs at the money, a spread's
 * other strike half a sigma out, a credit spread's short strike half a
 * sigma out and its long one a full sigma. Without an IV the "sigma"
 * steps fall to the next strikes out. A rule for a starting point, not a
 * recommendation; every strike can be changed. Null when the chain has no
 * strikes to fit.
 */
export function templateLegs(template: Template, chain: ExpiryChain): Leg[] | null {
  const calls = quotedStrikes(chain.rows, "call", 1);
  const puts = quotedStrikes(chain.rows, "put", 1);
  const callsToSell = quotedStrikes(chain.rows, "call", -1);
  const putsToSell = quotedStrikes(chain.rows, "put", -1);
  const f = chain.forward;
  const sigma = oneSigma(chain) ?? 0;
  const up = (n: number) => f * Math.exp(n * sigma);
  const above = (strikes: number[], target: number, than: number) => nearest(strikes.filter((k) => k > than), target);
  const below = (strikes: number[], target: number, than: number) => nearest(strikes.filter((k) => k < than), target);
  const leg = (kind: OptionKind, side: Side, strike: number | null): Leg | null => (strike === null ? null : { kind, side, strike });

  const build = (): (Leg | null)[] => {
    switch (template) {
      case "long_call":
        return [leg("call", 1, nearest(calls, f))];
      case "long_put":
        return [leg("put", 1, nearest(puts, f))];
      case "bull_call": {
        const long = nearest(calls, f);
        return long === null ? [null] : [leg("call", 1, long), leg("call", -1, above(callsToSell, up(0.5), long))];
      }
      case "bear_put": {
        const long = nearest(puts, f);
        return long === null ? [null] : [leg("put", 1, long), leg("put", -1, below(putsToSell, up(-0.5), long))];
      }
      case "bull_put": {
        const short = nearest(putsToSell, up(-0.5));
        return short === null ? [null] : [leg("put", -1, short), leg("put", 1, below(puts, up(-1), short))];
      }
      case "bear_call": {
        const short = nearest(callsToSell, up(0.5));
        return short === null ? [null] : [leg("call", -1, short), leg("call", 1, above(calls, up(1), short))];
      }
      case "iron_condor": {
        const shortPut = nearest(putsToSell, up(-0.5));
        if (shortPut === null) return [null];
        const shortCall = above(callsToSell, up(0.5), shortPut);
        if (shortCall === null) return [null];
        return [
          leg("put", 1, below(puts, up(-1), shortPut)),
          leg("put", -1, shortPut),
          leg("call", -1, shortCall),
          leg("call", 1, above(calls, up(1), shortCall)),
        ];
      }
    }
  };
  const legs = build();
  return legs.every((l): l is Leg => l !== null) ? legs : null;
}
