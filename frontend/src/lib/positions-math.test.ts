import { describe, expect, it } from "vitest";

import GOLDEN from "./options-strategy.golden.json";
import { black76 } from "./options-pricing";
import { type Smile, probProfit } from "./options-strategy";
import type { PositionGroup, PositionLeg } from "./owner-schemas";
import {
  type Market,
  NO_CHANGE,
  breakevens,
  costBasis,
  expiryClose,
  firstExpiry,
  greeks,
  historicalShare,
  legValue,
  markValue,
  pnlAtExpiry,
  pnlInScenario,
  profitChance,
  sessionsUntil,
  valueAt,
} from "./positions-math";

const NOW = new Date("2026-11-16T15:00:00Z"); // a Monday, in the session
const EXPIRY = "2026-12-18";
const LATER = "2027-01-15";
const MARKET: Market = { spot: 200, rate: 0.04, carry: 0.04, now: NOW };

function option(kind: "call" | "put", strike: number, quantity: number, average: number, extra: Partial<PositionLeg> = {}): PositionLeg {
  return {
    account: 1, kind, symbol: `X ${kind} ${strike}`, expiry: EXPIRY, strike, quantity, multiplier: 100, average_open: average,
    adjusted: false,
    quote: { bid: null, ask: null, mark: average, iv: 0.4, delta: kind === "call" ? 0.5 : -0.5, gamma: 0.02, theta: -0.1, vega: 0.25, updated_at: null },
    ...extra,
  };
}

function stock(quantity: number, average: number): PositionLeg {
  return { account: 1, kind: "stock", symbol: "X", expiry: null, strike: null, quantity, multiplier: 1, average_open: average, adjusted: false, quote: null };
}

function group(legs: PositionLeg[]): PositionGroup {
  const expiries = [...new Set(legs.map((l) => l.expiry).filter((e): e is string => e !== null))].sort();
  return { underlying: "X", symbol: "X", quote: { bid: null, ask: null, mark: 200, iv: null, delta: null, gamma: null, theta: null, vega: null, updated_at: null }, expiries, legs };
}

describe("Black-76, held to Python (tests/test_options_strategy_golden.py)", () => {
  it("prices to within the normal CDF's own error", () => {
    for (const c of GOLDEN.black76) {
      const price = black76(c.forward, c.strike, c.years, c.vol, c.discount, c.call);
      expect(Math.abs(price - c.price)).toBeLessThan(2e-7 * (c.forward + c.strike));
    }
  });

  it("is the discounted intrinsic value at expiry or with no volatility", () => {
    expect(black76(110, 100, 0, 0.3, 0.99, true)).toBeCloseTo(9.9, 10);
    expect(black76(90, 100, 0.5, 0, 1, false)).toBe(10);
    expect(black76(110, 100, 0, 0.3, 1, false)).toBe(0);
  });
});

describe("a position's value", () => {
  it("values an option at expiry at its intrinsic value and a share at the price", () => {
    const call = option("call", 190, 1, 5);
    expect(legValue(call, 205, expiryClose(EXPIRY), 0, MARKET)).toBe(15);
    expect(legValue(stock(10, 150), 205, NOW, 0, MARKET)).toBe(205);
  });

  it("can't value a leg before expiry without its IV, and says so", () => {
    const blind = option("call", 190, 1, 5, { quote: null });
    expect(legValue(blind, 205, NOW, 0, MARKET)).toBeNull();
    expect(valueAt(group([blind]), 205, NOW, 0, MARKET)).toBeNull();
  });

  it("won't model an adjusted contract", () => {
    expect(valueAt(group([option("call", 190, 1, 5, { adjusted: true })]), 205, NOW, 0, MARKET)).toBeNull();
  });

  it("counts what opening cost, short legs as money taken in", () => {
    expect(costBasis(group([option("call", 200, -2, 4.1), stock(200, 150.25)]))).toBeCloseTo(-820 + 30_050, 6);
    expect(costBasis(group([option("call", 200, 1, 2.5, { average_open: null })]))).toBeNull();
  });

  it("is worth its marks now", () => {
    expect(markValue(group([option("call", 200, -2, 4.1), stock(200, 150.25)]))).toBeCloseTo(-820 + 200 * 200, 6);
  });
});

describe("profit and loss", () => {
  it("of a long call at expiry", () => {
    expect(pnlAtExpiry(group([option("call", 200, 1, 2.5)]), 210, MARKET)).toBeCloseTo(750, 6);
    expect(pnlAtExpiry(group([option("call", 200, 1, 2.5)]), 180, MARKET)).toBeCloseTo(-250, 6);
  });

  it("of a covered call at expiry", () => {
    const covered = group([stock(100, 150), option("call", 200, -1, 4)]);
    expect(pnlAtExpiry(covered, 250, MARKET)).toBeCloseTo(25_000 - 5_000 - (15_000 - 400), 6);
  });

  it("in a what-if that runs to expiry is the expiry P&L at that price", () => {
    const call = group([option("call", 200, 1, 2.5)]);
    const days = (expiryClose(EXPIRY).getTime() - NOW.getTime()) / 86_400_000;
    expect(pnlInScenario(call, { move: 0.05, ivShift: 0, days }, MARKET)).toBeCloseTo(pnlAtExpiry(call, 210, MARKET)!, 6);
  });

  it("rises with IV for a long option and falls with time", () => {
    const call = group([option("call", 200, 1, 2.5)]);
    const now = pnlInScenario(call, NO_CHANGE, MARKET)!;
    expect(pnlInScenario(call, { ...NO_CHANGE, ivShift: 0.1 }, MARKET)!).toBeGreaterThan(now);
    expect(pnlInScenario(call, { ...NO_CHANGE, days: 10 }, MARKET)!).toBeLessThan(now);
  });

  it("finds a long call's breakeven at strike plus premium", () => {
    const [be] = breakevens(group([option("call", 200, 1, 2.5)]), MARKET);
    expect(be).toBeCloseTo(202.5, 1);
  });

  it("values a later leg at the first expiry, not at its own", () => {
    const calendar = group([option("call", 200, -1, 3), option("call", 200, 1, 6, { expiry: LATER })]);
    // At the first expiry the short call is worthless; the long one has 28 days left.
    const years = 28 / 365;
    const longLeft = black76(200 * Math.exp(0.04 * years), 200, years, 0.4, Math.exp(-0.04 * years), true);
    expect(pnlAtExpiry(calendar, 200, MARKET)).toBeCloseTo(longLeft * 100 - (600 - 300), 6);
  });
});

describe("Greeks in dollars", () => {
  it("adds legs by size, a share's delta being 1", () => {
    const g = greeks(group([option("call", 200, -2, 4.1), stock(200, 150)]), 200);
    expect(g.deltaShares).toBeCloseTo(-100 + 200, 6);
    expect(g.deltaDollars).toBeCloseTo(100 * 200 * 0.01, 6);
    expect(g.gammaShares).toBeCloseTo(-2 * 100 * 0.02 * 200 * 0.01, 6);
    expect(g.thetaDay).toBeCloseTo(20, 6);
    expect(g.vegaPoint).toBeCloseTo(-50, 6);
  });

  it("gives no total when a leg's Greek is missing", () => {
    const g = greeks(group([option("call", 200, 1, 2.5, { quote: null })]), 200);
    expect(g).toEqual({ deltaShares: null, deltaDollars: null, gammaShares: null, thetaDay: null, vegaPoint: null });
  });
});

describe("what the market prices", () => {
  const smile: Smile = { forward: 200, years: 32 / 365, points: [[-0.3, 0.5], [0, 0.4], [0.3, 0.45]] };

  it("agrees with the strategy builder for a plain option position", () => {
    const g = group([option("call", 200, 1, 2.5)]);
    const builder = probProfit([{ kind: "call", side: 1, strike: 200, premium: 2.5 }], smile);
    expect(profitChance(g, smile, MARKET)).toBeCloseTo(builder, 2);
  });

  it("covers a covered call too", () => {
    const chance = profitChance(group([stock(100, 150), option("call", 200, -1, 4)]), smile, MARKET)!;
    expect(chance).toBeGreaterThan(0.9); // bought far below the market
  });

  it("isn't given for a spread across expiries", () => {
    expect(profitChance(group([option("call", 200, -1, 3), option("call", 200, 1, 6, { expiry: LATER })]), smile, MARKET)).toBeNull();
  });
});

describe("what history shows", () => {
  it("counts the windows whose move would have paid", () => {
    const flat = Array.from({ length: 60 }, () => 100);
    const result = historicalShare(group([option("call", 200, 1, 2.5)]), flat, 10, MARKET);
    expect(result).toEqual({ share: 0, windows: 50 }); // no move: the premium is lost every time
    const doubling = Array.from({ length: 60 }, (_, i) => 100 * 1.02 ** i);
    expect(historicalShare(group([option("call", 200, 1, 2.5)]), doubling, 10, MARKET)?.share).toBe(1);
  });

  it("says nothing from too few windows", () => {
    expect(historicalShare(group([option("call", 200, 1, 2.5)]), [100, 101, 102], 1, MARKET)).toBeNull();
  });

  it("takes the first expiry by date, whatever order they came in", () => {
    const later = { ...group([option("call", 200, 1, 2.5, { expiry: LATER })]), expiries: [LATER, EXPIRY] };
    expect(firstExpiry(later)).toBe(EXPIRY);
  });

  it("counts the sessions left, weekends out", () => {
    expect(sessionsUntil("2026-11-20", NOW)).toBe(4);
    expect(sessionsUntil("2026-11-23", NOW)).toBe(5);
  });
});
