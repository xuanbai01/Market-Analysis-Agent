/**
 * formatClaimValue tests. The display rules here mirror the backend's
 * eval rubric (``tests/evals/rubric.py::_matches_claim``); both must
 * stay in step.
 */
import { describe, it, expect } from "vitest";
import { formatClaimValue } from "./format";

describe("formatClaimValue", () => {
  it("renders null as an em-dash", () => {
    expect(formatClaimValue(null)).toBe("—");
  });

  it("renders strings verbatim", () => {
    expect(formatClaimValue("AAPL")).toBe("AAPL");
    expect(formatClaimValue("2026-05-01")).toBe("2026-05-01");
  });

  it("renders booleans as yes/no", () => {
    expect(formatClaimValue(true)).toBe("yes");
    expect(formatClaimValue(false)).toBe("no");
  });

  it("renders fractions in [-1, 1] as percentages", () => {
    expect(formatClaimValue(0.18)).toBe("18.00%");
    expect(formatClaimValue(-0.05)).toBe("-5.00%");
    expect(formatClaimValue(1.0)).toBe("100.00%");
  });

  it("does not render zero as a percentage", () => {
    // 0 isn't usefully a percentage. Show it as "0".
    expect(formatClaimValue(0)).toBe("0");
  });

  it("abbreviates trillions / billions / millions", () => {
    expect(formatClaimValue(2_780_000_000_000)).toBe("2.78T");
    expect(formatClaimValue(95_300_000_000)).toBe("95.30B");
    expect(formatClaimValue(4_500_000)).toBe("4.50M");
    expect(formatClaimValue(-12_000_000)).toBe("-12.00M");
  });

  it("renders integers with locale grouping", () => {
    // 251 won't have grouping; 12345 will.
    expect(formatClaimValue(251)).toBe("251");
    expect(formatClaimValue(12345)).toBe("12,345");
  });

  it("renders mid-sized decimals to 2 places", () => {
    expect(formatClaimValue(28.567)).toBe("28.57");
    expect(formatClaimValue(33.92)).toBe("33.92");
  });
});

// ── Phase 4.3.X: unit-aware dispatch ─────────────────────────────────
//
// Backend Claim now carries an optional ``unit`` hint that drives
// frontend formatting deterministically. The legacy heuristic stays as
// the fallback for pre-4.3.X cached rows (``unit === undefined`` or
// ``null``), so all of the tests above keep passing unchanged.
//
// Each unit category is a regression test for one specific dogfood bug:
//   - ``fraction`` for ROE > 1 (prior bug: rendered "1.41" no suffix).
//   - ``percent`` for yfinance-style dividendYield (prior bug: 0.39
//     rendered "39.00%" instead of "0.39%").
//   - ``usd_per_share`` for capex/sbc per share < $1 (prior bug:
//     0.16 rendered "16.00%" instead of "$0.16").
//   - ``usd`` for market_cap (must abbreviate as "$4.11T" with $).
//   - ``ratio`` for P/E (no suffix).
//   - ``shares`` for shares-counted (abbreviated count, no $).

describe("formatClaimValue with unit hint", () => {
  it("dispatches fraction → ×100 and % suffix even when |value| > 1", () => {
    // The ROE-class bug: 1.41 used to render as "1.41" with no suffix.
    expect(formatClaimValue(1.41, "fraction")).toBe("141.00%");
    expect(formatClaimValue(0.18, "fraction")).toBe("18.00%");
    expect(formatClaimValue(-0.05, "fraction")).toBe("-5.00%");
  });

  it("dispatches percent → just append %, no ×100", () => {
    // The dividend-yield bug: yfinance returns 0.39 meaning 0.39%.
    // Prior formatter assumed [-1, 1] = fraction → 39.00%.
    expect(formatClaimValue(0.39, "percent")).toBe("0.39%");
    expect(formatClaimValue(2.5, "percent")).toBe("2.50%");
    expect(formatClaimValue(0, "percent")).toBe("0.00%");
  });

  it("dispatches usd_per_share → $ prefix + 2 decimals", () => {
    // The per-share-dollar bug: 0.16 used to render as "16.00%".
    expect(formatClaimValue(0.16, "usd_per_share")).toBe("$0.16");
    expect(formatClaimValue(3.48, "usd_per_share")).toBe("$3.48");
    expect(formatClaimValue(-0.04, "usd_per_share")).toBe("-$0.04");
  });

  it("dispatches usd → abbreviate large + $ prefix", () => {
    expect(formatClaimValue(4_111_000_000_000, "usd")).toBe("$4.11T");
    expect(formatClaimValue(95_300_000_000, "usd")).toBe("$95.30B");
    expect(formatClaimValue(921.04, "usd")).toBe("$921.04");
  });

  it("dispatches ratio → plain numeric, 2 decimals, no suffix", () => {
    expect(formatClaimValue(33.92, "ratio")).toBe("33.92");
    expect(formatClaimValue(1.4, "ratio")).toBe("1.40");
  });

  it("dispatches shares → abbreviated count, no $ prefix", () => {
    expect(formatClaimValue(134_420_000, "shares")).toBe("134.42M");
    expect(formatClaimValue(1_500, "shares")).toBe("1,500");
  });

  it("dispatches string / date → passthrough", () => {
    expect(formatClaimValue("Apple Inc.", "string")).toBe("Apple Inc.");
    expect(formatClaimValue("2026-07-30", "date")).toBe("2026-07-30");
  });

  it("dispatches count → integer locale grouping", () => {
    expect(formatClaimValue(12_345, "count")).toBe("12,345");
  });

  it("falls back to legacy heuristic when unit is undefined", () => {
    // Pre-4.3.X cached rows have no unit field → behavior unchanged.
    expect(formatClaimValue(0.18)).toBe("18.00%");
    expect(formatClaimValue(33.92)).toBe("33.92");
    expect(formatClaimValue(2_780_000_000_000)).toBe("2.78T");
  });

  it("falls back to legacy heuristic when unit is null", () => {
    // Backend defaults `unit` to null on backwards-compat rows.
    expect(formatClaimValue(0.18, null)).toBe("18.00%");
  });

  it("renders null-value verbatim regardless of unit", () => {
    expect(formatClaimValue(null, "fraction")).toBe("—");
    expect(formatClaimValue(null, "usd_per_share")).toBe("—");
  });
});
