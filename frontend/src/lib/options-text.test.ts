import { describe, expect, it } from "vitest";

import {
  coneSentence,
  daysLabel,
  daysUntil,
  earningsSentence,
  expiryKind,
  expiryLabel,
  openInterestSentence,
  smileSentence,
  termSentence,
  type Sentence,
} from "./options-text";
import type { EarningsBlock, ExpiryChain, ExpirySummary } from "./options-schemas";

const text = (s: Sentence | null) => (s === null ? null : s.map((p) => (typeof p === "string" ? p : `**${p.strong}**`)).join(""));

function summary(expiry: string, days: number, atm_iv: number, expected_move = 0.1): ExpirySummary {
  return {
    expiry, days, sessions: Math.round(days * 0.7), forward: 100, forward_from_parity: true, atm_iv, expected_move,
    low: 90, high: 110, straddle: null, straddle_strike: null, call_open_interest: 0, put_open_interest: 0,
    call_volume: 0, put_volume: 0, includes_earnings: false,
  } as ExpirySummary;
}

describe("expiryKind", () => {
  it("calls the third Friday monthly and other days weekly", () => {
    expect(expiryKind("2026-11-20")).toBe("monthly"); // third Friday of November 2026
    expect(expiryKind("2026-12-18")).toBe("monthly");
    expect(expiryKind("2026-11-27")).toBe("weekly"); // fourth Friday
    expect(expiryKind("2026-11-16")).toBe("weekly"); // a Monday
    expect(expiryKind("2026-11-19")).toBe("weekly"); // the Thursday before a regular third Friday
  });

  it("moves the monthly to Thursday when the third Friday is Good Friday", () => {
    // 2025: Easter April 20, Good Friday April 18, the third Friday of April.
    expect(expiryKind("2025-04-18")).toBe("weekly");
    expect(expiryKind("2025-04-17")).toBe("monthly");
  });

  it("moves the monthly to Thursday when the third Friday is Juneteenth", () => {
    // 2026-06-19 is a Friday, the third of June.
    expect(expiryKind("2026-06-18")).toBe("monthly");
    expect(expiryKind("2026-06-19")).toBe("weekly");
  });
});

describe("labels", () => {
  it("counts days and names the expiry", () => {
    expect(daysLabel(1)).toBe("1 day");
    expect(daysLabel(0.4)).toBe("0 days");
    expect(daysLabel(5.2)).toBe("5 days");
    expect(daysUntil("2026-11-15T21:00:00Z", "2026-11-20")).toBe(5);
    expect(expiryLabel("2026-11-20", 5)).toBe("Nov 20, 2026 · 5 days · monthly");
    expect(expiryLabel("2026-11-27", 12)).toBe("Nov 27, 2026 · 12 days · weekly");
  });
});

describe("sentences", () => {
  it("gives the cone's move for the expiry nearest 30 days", () => {
    const expiries = [summary("2026-11-20", 5, 0.7, 0.05), summary("2026-12-11", 26, 0.6, 0.167), summary("2027-01-15", 61, 0.55, 0.22)];
    expect(text(coneSentence(expiries, 162.92))).toBe(
      "Options price a **±16.7% ($27.21)** move by **Dec 11**, one standard deviation: option prices put about a two-in-three chance on the price ending inside it.",
    );
    expect(coneSentence([], 100)).toBeNull();
  });

  it("names the term structure's slope from the numbers", () => {
    const down = [summary("2026-11-20", 5, 0.8), summary("2026-11-27", 12, 0.63), summary("2027-05-21", 187, 0.48)];
    expect(text(termSentence(down))).toBe(
      "At-the-money IV runs from **63.0%** at 12 days to **48.0%** at 187 days, sloping down: near expiries price more movement than far ones.",
    );
    const up = [summary("2026-11-27", 12, 0.3), summary("2027-05-21", 187, 0.4)];
    expect(text(termSentence(up))).toContain("sloping up");
    const flat = [summary("2026-11-27", 12, 0.3), summary("2027-05-21", 187, 0.302)];
    expect(text(termSentence(flat))).toContain("about flat");
    expect(termSentence([summary("2026-11-27", 12, 0.3)])).toBeNull();
  });

  it("states the skew's side in words", () => {
    expect(text(smileSentence(0.027))).toBe("25Δ puts are priced **2.7 points** above 25Δ calls: downside protection costs more.");
    expect(text(smileSentence(-0.011))).toBe("25Δ puts are priced **1.1 points** below 25Δ calls: upside calls cost more.");
    expect(text(smileSentence(0.0001))).toBe("25Δ puts and calls are priced at about the same IV.");
    expect(smileSentence(null)).toBeNull();
  });

  it("names the largest call and put strikes near the money", () => {
    const chain = {
      expiry: "2026-12-11", days: 26, forward: 163, atm_iv: 0.6, smile: [], rows: [],
      open_interest: [{ strike: 150, call: 275, put: 3912 }, { strike: 185, call: 8099, put: 955 }],
    } as unknown as ExpiryChain;
    expect(text(openInterestSentence(chain))).toBe("Most open near the money: **$185.00 calls (8,099)** and **$150.00 puts (3,912)**.");
    expect(openInterestSentence({ ...chain, open_interest: [] })).toBeNull();
    expect(openInterestSentence({ ...chain, open_interest: [{ strike: 150, call: 0, put: 0 }] })).toBeNull();
  });

  it("puts the next report's priced move beside past ones, singular and plural", () => {
    const base = {
      next_date: "2026-11-17", next_timing: "after_close", estimated: false, reaction_date: "2026-11-18",
      implied_move: 0.0712, implied_move_usd: 11.59, event_sigma: 0.089, base_vol: 0.5, method: "before_and_after",
      refused: null, expiries: [], past: [{ announced: "2026-08-27", timing: "after_close", move: -0.03, spans_extra_day: false }],
      past_mean_abs: 0.0404,
    } as unknown as EarningsBlock;
    expect(text(earningsSentence(base))).toBe("Options price the **Nov 17** report at about **±7.1%**; the last report moved **4.0%**.");
    const eight = { ...base, past: Array(8).fill(base.past[0]) };
    expect(text(earningsSentence(eight))).toContain("the last 8 reports moved **4.0%** on average.");
    expect(earningsSentence({ ...base, implied_move: null })).toBeNull();
  });
});
