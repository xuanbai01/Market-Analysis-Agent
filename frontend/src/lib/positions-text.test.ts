import { describe, expect, it } from "vitest";

import type { EarningsBlock } from "./options-schemas";
import type { Sentence } from "./options-text";
import type { PositionGroup, PositionLeg } from "./owner-schemas";
import { NO_CHANGE } from "./positions-math";
import {
  earningsSentence,
  greeksSentence,
  groupSentence,
  historySentence,
  legLabel,
  marketSentence,
  scenarioSentence,
  signedUsd,
} from "./positions-text";

const text = (s: Sentence | null) => (s === null ? null : s.map((p) => (typeof p === "string" ? p : `**${p.strong}**`)).join(""));

const call: PositionLeg = {
  account: 1, kind: "call", symbol: "NVDA  261218C00200000", expiry: "2026-12-18", strike: 200, quantity: -2, multiplier: 100,
  average_open: 4.1, adjusted: false, expires_at: null, quote: null,
};
const shares: PositionLeg = { ...call, kind: "stock", symbol: "NVDA", expiry: null, strike: null, quantity: 200, multiplier: 1, average_open: 150 };
const group: PositionGroup = { underlying: "NVDA", symbol: "NVDA", quote: null, expiries: ["2026-12-18"], legs: [shares, call] };

describe("position words", () => {
  it("signs dollars and rounds them", () => {
    expect([signedUsd(1320.4), signedUsd(-820), signedUsd(0.2)]).toEqual(["+$1,320", "−$820", "$0"]);
  });

  it("names each leg the way a trader says it", () => {
    expect(legLabel(call)).toBe("2 short Dec 18 $200 calls");
    expect(legLabel({ ...call, quantity: 1, kind: "put", strike: 187.5 })).toBe("1 long Dec 18 $187.5 put");
    expect(legLabel(shares)).toBe("200 shares");
    expect(legLabel({ ...shares, quantity: -50 })).toBe("50 shares short");
    expect(legLabel({ ...call, adjusted: true })).toBe("2 short Dec 18 $200 calls (adjusted)");
  });

  it("says what's held, its worth and the P&L since it was opened", () => {
    expect(text(groupSentence(group, 31_000, 29_180))).toBe(
      "NVDA: 200 shares and 2 short Dec 18 $200 calls. Worth **$31,000** at tastytrade's marks, **+$1,820** since it was opened.",
    );
    expect(text(groupSentence(group, null, 29_180))).toBe("NVDA: 200 shares and 2 short Dec 18 $200 calls.");
  });

  it("puts the Greeks as P&L", () => {
    expect(text(greeksSentence({ deltaShares: 138, deltaDollars: 225, gammaShares: -8, thetaDay: 20, vegaPoint: -50 }))).toBe(
      "Moves like **138 shares**: **+$225** for a 1% rise, which itself changes by **−8 shares** per 1%. A day passing: **+$20**. IV one point higher: **−$50**.",
    );
    expect(greeksSentence({ deltaShares: null, deltaDollars: null, gammaShares: null, thetaDay: null, vegaPoint: null })).toBeNull();
    // Rounded first, then signed: no "−0".
    expect(text(greeksSentence({ deltaShares: -0.4, deltaDollars: -0.6, gammaShares: null, thetaDay: null, vegaPoint: null }))).toMatch(/^Moves like \*\*0 shares\*\*/);
    expect(text(greeksSentence({ deltaShares: -42.6, deltaDollars: -70, gammaShares: null, thetaDay: null, vegaPoint: null }))).toMatch(/^Moves like \*\*−43 shares\*\*/);
    expect(text(greeksSentence({ deltaShares: 10, deltaDollars: 16, gammaShares: -0.5, thetaDay: null, vegaPoint: null }))).not.toMatch(/changes by/);
  });

  it("words a what-if", () => {
    expect(text(scenarioSentence("NVDA", NO_CHANGE, 162.9, 1200))).toBe("At today's price and IVs, the model puts the P&L at **+$1,200**.");
    expect(text(scenarioSentence("NVDA", { move: -0.05, ivShift: -0.1, days: 7 }, 154.755, -410))).toBe(
      "With NVDA **5% lower ($154.76)**, IV **10 points lower** in **7 days**, the P&L would be **−$410**.",
    );
    expect(text(scenarioSentence("NVDA", { move: 0, ivShift: 0, days: 1 }, 162.9, -20))).toBe("In **1 day**, the P&L would be **−$20**.");
    expect(text(scenarioSentence("NVDA", NO_CHANGE, 162.9, null))).toMatch(/can't be valued before expiry/);
  });

  it("labels the market's chance and history's share for what they are", () => {
    expect(text(marketSentence(0.432, "2026-12-18", false))).toBe(
      "Option prices put the chance this is in profit at **Dec 18**'s close at **43%**: what the market implies, not a forecast.",
    );
    expect(text(marketSentence(null, null, true))).toMatch(/no single chance of profit for a spread across expiries/);
    expect(text(historySentence("NVDA", { share: 0.381, windows: 1234 }, 23))).toBe(
      "Over the last 5 years, NVDA's moves across 23 sessions would have left it in profit **38%** of the time (1,234 windows): past moves, not a forecast.",
    );
    expect(historySentence("NVDA", null, 23)).toBeNull();
  });

  it("mentions a report only when it falls before the first expiry", () => {
    const earnings = {
      next_date: "2026-11-19", next_timing: null, estimated: false, reaction_date: null, implied_move: 0.071, implied_move_usd: null,
      event_sigma: null, base_vol: null, method: null, refused: null, expiries: [],
      past: [{ announced: "2026-08-27", timing: "amc", move: -0.03, spans_extra_day: false }], past_mean_abs: 0.062,
    } as unknown as EarningsBlock;
    expect(text(earningsSentence("NVDA", earnings, "2026-12-18"))).toBe(
      "NVDA reports on **Nov 19**, before this position's first expiry: options imply a **±7.1%** move for it; the last 1 moved **6.2%** on average.",
    );
    expect(earningsSentence("NVDA", earnings, "2026-11-18")).toBeNull();
    // On the expiry day: after the close, the position has expired before the market trades on it.
    const afterClose = { ...earnings, next_timing: "after_close", reaction_date: "2026-11-20" } as EarningsBlock;
    expect(earningsSentence("NVDA", afterClose, "2026-11-19")).toBeNull();
    const beforeOpen = { ...earnings, next_timing: "before_open", reaction_date: "2026-11-19" } as EarningsBlock;
    expect(earningsSentence("NVDA", beforeOpen, "2026-11-19")).not.toBeNull();
    expect(text(earningsSentence("NVDA", { ...earnings, implied_move: null, refused: "the expiries are too far" }, "2026-12-18"))).toMatch(
      /\(no implied move: the expiries are too far\)/,
    );
  });
});
