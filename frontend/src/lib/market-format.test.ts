import { describe, expect, it } from "vitest";

import {
  formatQuoteChange,
  formatQuotePrice,
  formatSessionDate,
  RATING_BANDS,
} from "./market-format";

describe("formatQuotePrice", () => {
  it("prints index points with grouping and 2 decimals", () => {
    expect(formatQuotePrice({ price: 7376.86, unit: "points" })).toBe("7,376.86");
    expect(formatQuotePrice({ price: 25.64, unit: "points" })).toBe("25.64");
  });

  it("prints a yield as a percent", () => {
    expect(formatQuotePrice({ price: 4.859, unit: "percent" })).toBe("4.86%");
  });

  it("prints dollars, dropping cents on large prices", () => {
    expect(formatQuotePrice({ price: 4073.7, unit: "usd" })).toBe("$4,073.70");
    expect(formatQuotePrice({ price: 74790.86, unit: "usd" })).toBe("$74,791");
  });
});

describe("formatQuoteChange", () => {
  it("states the day's move in percent with a direction", () => {
    expect(formatQuoteChange({ change: 23.13, change_percent: 0.3146, unit: "points" })).toEqual({
      text: "+0.31%",
      direction: "up",
    });
    expect(formatQuoteChange({ change: -956.7, change_percent: -1.263, unit: "usd" })).toEqual({
      text: "-1.26%",
      direction: "down",
    });
  });

  it("moves a yield in basis points", () => {
    expect(formatQuoteChange({ change: 0.022, change_percent: 0.45, unit: "percent" })).toEqual({
      text: "+2 bps",
      direction: "up",
    });
  });

  it("calls a move that rounds to zero flat", () => {
    expect(formatQuoteChange({ change: 0.001, change_percent: 0.001, unit: "points" })).toEqual({
      text: "0.00%",
      direction: "flat",
    });
  });
});

describe("formatSessionDate", () => {
  it("reads the date as a calendar day, whatever the timezone", () => {
    expect(formatSessionDate("2026-11-06")).toBe("Nov 6");
  });
});

describe("RATING_BANDS", () => {
  it("covers 0–100 without gaps", () => {
    expect(RATING_BANDS[0].from).toBe(0);
    expect(RATING_BANDS[RATING_BANDS.length - 1].to).toBe(100);
    for (let i = 1; i < RATING_BANDS.length; i++) {
      expect(RATING_BANDS[i].from).toBe(RATING_BANDS[i - 1].to);
    }
  });
});
