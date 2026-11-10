import { describe, expect, it } from "vitest";

import { shortClaimName } from "./thesis";

describe("shortClaimName", () => {
  it.each([
    ["EPS growth, last 4 quarters vs the 4 before", "EPS growth"],
    ["Operating income per share growth, 2025-Q3 → 2026-Q3", "Operating income per share growth"],
    ["PEG ratio (P/E to growth, trailing)", "PEG ratio"],
    ["Free cash flow ÷ net income (trailing 12 months)", "Free cash flow ÷ net income"],
    ["Trailing P/E vs peer median of 21.36: premium (+) or discount (−)", "Trailing P/E vs peer median"],
    ["Gross margin vs peer median of 50.59%", "Gross margin vs peer median"],
    ["Return on equity", "Return on equity"],
  ])("%s → %s", (description, expected) => {
    expect(shortClaimName(description)).toBe(expected);
  });

  it("falls back to the full description when cutting leaves nothing", () => {
    expect(shortClaimName("(unnamed)")).toBe("(unnamed)");
  });
});
