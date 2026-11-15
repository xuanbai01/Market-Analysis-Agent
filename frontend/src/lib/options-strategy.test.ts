import { describe, expect, it } from "vitest";

import { RAW_OPTIONS_REPORT } from "../components/options/fixture";
import GOLDEN from "./options-strategy.golden.json";
import { ExpiryChainSchema } from "./options-schemas";
import {
  type Leg,
  type PricedLeg,
  type Smile,
  TEMPLATES,
  analyse,
  breakevens,
  extremes,
  normCdf,
  payoff,
  premium,
  probAbove,
  probProfit,
  smileOf,
  templateLegs,
} from "./options-strategy";

const CHAIN = ExpiryChainSchema.parse(RAW_OPTIONS_REPORT.chain);

const smiles: Record<string, Smile> = Object.fromEntries(
  Object.entries(GOLDEN.smiles).map(([name, s]) => [
    name,
    { forward: s.forward, years: s.years, points: s.points.map(([x, iv]) => [x, iv] as [number, number]) },
  ]),
);

const priced = (legs: { kind: string; side: number; strike: number; premium: number }[]): PricedLeg[] =>
  legs.map((l) => ({ kind: l.kind as "call" | "put", side: l.side as 1 | -1, strike: l.strike, premium: l.premium }));

describe("held to the Python numbers (tests/test_options_strategy_golden.py)", () => {
  it("normCdf to 1e-6", () => {
    for (const { x, p } of GOLDEN.norm_cdf) expect(Math.abs(normCdf(x) - p)).toBeLessThan(1e-6);
  });

  it("the chance of ending above a strike, skew included, to 1e-6", () => {
    for (const c of GOLDEN.prob_above) {
      expect(Math.abs(probAbove(smiles[c.smile], c.strike) - c.prob)).toBeLessThan(1e-6);
    }
  });

  it("the probability of profit to 1e-4", () => {
    for (const c of GOLDEN.pop) {
      expect(Math.abs(probProfit(priced(c.legs), smiles[c.smile]) - c.pop)).toBeLessThan(1e-4);
    }
  });
});

describe("payoff at expiry, per share", () => {
  const call = (side: 1 | -1, strike: number, p: number): PricedLeg => ({ kind: "call", side, strike, premium: p });
  const put = (side: 1 | -1, strike: number, p: number): PricedLeg => ({ kind: "put", side, strike, premium: p });

  it("a long call: one breakeven, unlimited profit, the premium at risk", () => {
    const legs = [call(1, 100, 5)];
    expect(payoff(legs, 110)).toBeCloseTo(5);
    expect(breakevens(legs)).toEqual([105]);
    expect(extremes(legs)).toEqual({ maxProfit: null, maxLoss: -5 });
  });

  it("a long put: profit capped at the strike less the premium", () => {
    const legs = [put(1, 100, 4)];
    expect(breakevens(legs)).toEqual([96]);
    expect(extremes(legs)).toEqual({ maxProfit: 96, maxLoss: -4 });
  });

  it("a bull call spread (debit)", () => {
    const legs = [call(1, 100, 5), call(-1, 110, 2)];
    expect(breakevens(legs)).toEqual([103]);
    expect(extremes(legs)).toEqual({ maxProfit: 7, maxLoss: -3 });
  });

  it("a bull put spread (credit)", () => {
    const legs = [put(-1, 100, 4), put(1, 90, 1.5)];
    expect(breakevens(legs)).toEqual([97.5]);
    const { maxProfit, maxLoss } = extremes(legs);
    expect(maxProfit).toBeCloseTo(2.5);
    expect(maxLoss).toBeCloseTo(-7.5);
  });

  it("an iron condor: two breakevens, the credit is the most it makes", () => {
    const legs = [put(1, 85, 0.5), put(-1, 90, 1.2), call(-1, 110, 1.3), call(1, 115, 0.6)];
    const [low, high] = breakevens(legs);
    expect(low).toBeCloseTo(88.6);
    expect(high).toBeCloseTo(111.4);
    const { maxProfit, maxLoss } = extremes(legs);
    expect(maxProfit).toBeCloseTo(1.4);
    expect(maxLoss).toBeCloseTo(-3.6);
  });

  it("a short call's loss has no floor", () => {
    expect(extremes([call(-1, 100, 3)])).toEqual({ maxProfit: 3, maxLoss: null });
  });

  it("a breakeven exactly on a strike is found once", () => {
    // Long the 100 call for 0 net of a 0-premium short: breakeven at 100.
    expect(breakevens([call(1, 100, 0)])).toEqual([100]);
  });
});

describe("prices", () => {
  it("mid needs an offer; natural buys at the ask and sells at the bid", () => {
    expect(premium({ bid: 1, ask: 1.2 }, 1, "mid")).toBeCloseTo(1.1);
    expect(premium({ bid: 1, ask: 1.2 }, 1, "natural")).toBe(1.2);
    expect(premium({ bid: 1, ask: 1.2 }, -1, "natural")).toBe(1);
    expect(premium({ bid: 0.4, ask: 0 }, 1, "mid")).toBeNull(); // nobody offers
    expect(premium({ bid: 0.4, ask: 0 }, 1, "natural")).toBeNull();
    expect(premium({ bid: 0, ask: 0 }, -1, "natural")).toBeNull(); // no quote at all
    expect(premium({ bid: 0, ask: 0.05 }, -1, "natural")).toBe(0); // nobody bids
  });
});

describe("smileOf", () => {
  it("merges points at the same moneyness", () => {
    const point = CHAIN.smile[3];
    const smile = smileOf({ ...CHAIN, smile: [...CHAIN.smile, { ...point, iv: point.iv + 0.02, side: "call" }] })!;
    expect(smile.points).toHaveLength(CHAIN.smile.length);
    expect(smile.points.find(([x]) => x === point.log_moneyness)![1]).toBeCloseTo(point.iv + 0.01);
  });
});

describe("a flat smile", () => {
  it("gives N(d2) for the chance of ending above", () => {
    const flat: Smile = { forward: 100, years: 1, points: [[-0.5, 0.2], [0.5, 0.2]] };
    expect(probAbove(flat, 100)).toBeCloseTo(normCdf(-0.1), 10);
  });
});

describe("templates on a real chain (NVDA)", () => {
  it("starts strikes by the rule: at the money, half a sigma and a sigma out", () => {
    // NVDA: forward 163.03, ATM IV 60.4%, 28 days: sigma is 16.7%, so half a
    // sigma out is 149.96 / 177.25 and a full sigma 137.95 / 192.70.
    const strikes = (t: keyof typeof TEMPLATES) => templateLegs(t, CHAIN)!.map((l) => l.strike);
    expect(strikes("long_call")).toEqual([165]);
    expect(strikes("bull_call")).toEqual([165, 175]);
    expect(strikes("bear_put")).toEqual([165, 150]);
    expect(strikes("bull_put")).toEqual([150, 140]);
    expect(strikes("bear_call")).toEqual([175, 190]);
    expect(strikes("iron_condor")).toEqual([140, 150, 175, 190]);
  });

  it("takes sigma from the smile when the chain has no ATM IV", () => {
    expect(templateLegs("bull_put", { ...CHAIN, atm_iv: null })!.map((l) => l.strike)).toEqual([150, 140]);
  });

  it("builds every template from strikes with quotes, in the right order", () => {
    for (const t of Object.keys(TEMPLATES) as (keyof typeof TEMPLATES)[]) {
      const legs = templateLegs(t, CHAIN);
      expect(legs, t).not.toBeNull();
      for (const leg of legs!) expect(CHAIN.rows.some((r) => r.strike === leg.strike)).toBe(true);
    }
    const condor = templateLegs("iron_condor", CHAIN)!;
    const [longPut, shortPut, shortCall, longCall] = condor.map((l) => l.strike);
    expect(longPut).toBeLessThan(shortPut);
    expect(shortPut).toBeLessThan(shortCall);
    expect(shortCall).toBeLessThan(longCall);
  });

  it("analyses a bull call spread at mid and at the natural price", () => {
    const legs = templateLegs("bull_call", CHAIN)!;
    const smile = smileOf(CHAIN)!;
    const mid = analyse(legs, CHAIN.rows, "mid", smile)!;
    const natural = analyse(legs, CHAIN.rows, "natural", smile)!;
    expect(mid.cost).toBeGreaterThan(0); // a debit
    expect(natural.cost).toBeGreaterThanOrEqual(mid.cost); // crossing the spread costs more
    expect(natural.pop!).toBeLessThanOrEqual(mid.pop!);
    expect(mid.breakevens).toHaveLength(1);
    expect(mid.maxProfit).not.toBeNull();
  });

  it("says a leg with no quote can't be priced", () => {
    const strike = CHAIN.rows[0].strike;
    const rows = CHAIN.rows.map((r) => (r.strike === strike ? { ...r, call_bid: 0, call_ask: 0 } : r));
    const legs: Leg[] = [{ kind: "call", side: 1, strike }];
    expect(analyse(legs, rows, "mid", smileOf(CHAIN))).toBeNull();
  });

  it("gives no probability without a smile, but still the payoff", () => {
    const legs = templateLegs("long_call", CHAIN)!;
    const result = analyse(legs, CHAIN.rows, "mid", null)!;
    expect(result.pop).toBeNull();
    expect(result.breakevens).toHaveLength(1);
  });
});
