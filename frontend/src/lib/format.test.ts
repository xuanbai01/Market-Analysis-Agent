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
