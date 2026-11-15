import { describe, expect, it } from "vitest";

import { fractionPctTick, usdBillionsTick, usdTick } from "./chart-format";

describe("axis ticks drop needless decimals", () => {
  it("writes whole percents bare and keeps the half of a 2.5% step", () => {
    expect([0, 0.025, 0.05, 0.075, 0.1, 0.125].map(fractionPctTick)).toEqual([
      "0%",
      "2.5%",
      "5%",
      "7.5%",
      "10%",
      "12.5%",
    ]);
    expect(fractionPctTick(-0.25)).toBe("-25%");
  });

  it("writes dollars per share bare when whole", () => {
    expect([0, 2, 2.5].map(usdTick)).toEqual(["$0", "$2", "$2.50"]);
  });

  it("writes billions bare when whole and keeps the half of a $2.5B step", () => {
    expect([0, 2.5e9, 5e9, 7.5e9, 10e9].map(usdBillionsTick)).toEqual(["$0", "$2.5B", "$5B", "$7.5B", "$10B"]);
    expect([100e9, 200e9].map(usdBillionsTick)).toEqual(["$100B", "$200B"]);
  });
});
