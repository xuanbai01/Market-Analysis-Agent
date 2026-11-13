/**
 * missing-data — what a report asked for and did not get, read from
 * ``tool_calls_audit`` (dogfood 2026-11 #18: XOM lost two cards and the
 * page only said "confidence: low").
 */
import { describe, expect, it } from "vitest";

import { missingFromAudit } from "./missing-data";

describe("missingFromAudit", () => {
  it("is empty when every tool came back with data", () => {
    expect(
      missingFromAudit(["fetch_fundamentals: ok", "fetch_peers: ok", "extract_10k_risks_diff: ok"]),
    ).toEqual([]);
  });

  it("names a tool that ran but found nothing", () => {
    expect(
      missingFromAudit([
        "extract_10k_risks_diff: empty",
        "fetch_annual_history: empty",
        "fetch_fundamentals: ok",
      ]),
    ).toEqual([
      { label: "10-K risk changes", reason: "empty" },
      { label: "ten-year history", reason: "empty" },
    ]);
  });

  it("names a tool that failed, and says so", () => {
    expect(missingFromAudit(["fetch_peers: error/RuntimeError", "fetch_macro: empty"])).toEqual([
      { label: "peer comparison", reason: "failed" },
      { label: "macro", reason: "empty" },
    ]);
  });

  it("leaves out the 10-K business extract, which no card shows", () => {
    expect(missingFromAudit(["extract_10k_business: empty"])).toEqual([]);
  });

  it("falls back to a readable name for a tool it has no label for", () => {
    expect(missingFromAudit(["fetch_insider_trades: empty"])).toEqual([
      { label: "insider trades", reason: "empty" },
    ]);
  });

  it("ignores entries it cannot read and reports written before 'empty' existed", () => {
    expect(missingFromAudit(["", "nonsense", "fetch_news: ok"])).toEqual([]);
    expect(missingFromAudit([])).toEqual([]);
  });
});
