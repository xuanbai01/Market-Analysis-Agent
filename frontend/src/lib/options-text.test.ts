import { describe, expect, it } from "vitest";

import {
  coneSentence,
  daysLabel,
  daysUntil,
  expiryKind,
  expiryLabel,
  openInterestSentence,
  smileSentence,
  termSentence,
  type Sentence,
} from "./options-text";
import type { ExpiryChain, ExpirySummary } from "./options-schemas";

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

  it("moves it too when Juneteenth is a Saturday, observed on Friday the 18th", () => {
    // 2027-06-19 is a Saturday: the market closes Friday 2027-06-18, the third Friday.
    expect(expiryKind("2027-06-18")).toBe("weekly");
    expect(expiryKind("2027-06-17")).toBe("monthly");
    // 2028-06-19 is a Monday (the 18th a Sunday): the third Friday, June 16, stands.
    expect(expiryKind("2028-06-16")).toBe("monthly");
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
    // The nearest expiry, a week out or not: the same end the chart draws.
    expect(text(termSentence(down))).toBe(
      "At-the-money IV runs from **80.0%** at 5 days to **48.0%** at 187 days, sloping down: near expiries price more movement than far ones.",
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
});
