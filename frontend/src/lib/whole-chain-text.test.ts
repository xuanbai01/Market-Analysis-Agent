import { describe, expect, it } from "vitest";

import type { WholeChain } from "./owner-schemas";
import { wholeChainNotes, wholeChainSentence } from "./whole-chain-text";

function chain(over: Partial<WholeChain> = {}): WholeChain {
  const expiry = (d: string) => ({
    expiry: d, days: 30, sessions: 20, forward: 100, forward_from_parity: true, atm_iv: 0.2, expected_move: 0.05,
    low: 95, high: 105, straddle: 4, straddle_strike: 100, call_open_interest: 10, put_open_interest: 8,
    call_volume: 0, put_volume: 0, includes_earnings: false, max_pain: 100, net_gex: 1000,
  });
  return {
    symbol: "SPY", spot: 670, quoted_at: "2026-11-16T15:00:00Z", as_of: "2026-11-16T15:00:01Z", updated_at: null,
    expiries: [expiry("2026-11-20"), expiry("2026-12-18"), expiry("2027-03-19")],
    positioning: {
      call_open_interest: 1_200_000, put_open_interest: 1_800_000, put_call: 1.5, top: [], max_pain: null, exposure: [],
      call_gex: 5e9, put_gex: -3e9, net_gex: 2e9, call_dex: 0, put_dex: 0, net_dex: 0, call_wall: 700, put_wall: 650,
      gamma_flip: 660, assumption: "dealers…",
    },
    max_days: 120, strike_range: 0.15, options_read: 4816, options_quoted: 4800, left_out: [], capped: false,
    source: "tastytrade",
    ...over,
  } as WholeChain;
}

const text = (s: ReturnType<typeof wholeChainSentence>) =>
  (s ?? []).map((part) => (typeof part === "string" ? part : part.strong)).join("");

describe("wholeChainSentence", () => {
  it("says what the read covers, the open interest and the chain's walls", () => {
    expect(text(wholeChainSentence(chain()))).toBe(
      "3 expiries read, out to Mar 19 (strikes within 15% of the price): 1,200,000 calls and 1,800,000 puts open " +
        "(put/call 1.50); the chain's call wall is $700 and its put wall $650.",
    );
  });

  it("says each wall whole when the chain has only one", () => {
    const callOnly = chain();
    callOnly.positioning = { ...callOnly.positioning, put_wall: null };
    expect(text(wholeChainSentence(callOnly))).toContain("; the chain's call wall is $700.");
    const putOnly = chain();
    putOnly.positioning = { ...putOnly.positioning, call_wall: null };
    expect(text(wholeChainSentence(putOnly))).toContain("; the chain's put wall is $650.");
  });

  it("counts one expiry as one", () => {
    expect(text(wholeChainSentence(chain({ expiries: chain().expiries.slice(0, 1) })))).toMatch(/^1 expiry read, out to Nov 20/);
  });

  it("has nothing to say without open interest", () => {
    const empty = chain();
    empty.positioning = { ...empty.positioning, call_open_interest: 0, put_open_interest: 0 };
    expect(wholeChainSentence(empty)).toBeNull();
  });
});

describe("wholeChainNotes", () => {
  it("names what was left out", () => {
    const notes = wholeChainNotes(chain({ left_out: ["2026-12-26"], capped: true }));
    expect(notes).toEqual([
      "No usable quotes for Dec 26: left out.",
      "More contracts than one read takes: the farthest expiries are left out.",
      "16 of 4,816 contracts sent no quote or open interest.",
    ]);
  });
});
