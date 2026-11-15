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

  it("keeps both decimals of a quarter-percent step", () => {
    // niceTicks steps by 0.25% on a narrow range; one decimal read "40.3%".
    expect([0.4, 0.4025, 0.405, 0.4075].map(fractionPctTick)).toEqual(["40%", "40.25%", "40.5%", "40.75%"]);
  });

  it("writes dollars per share bare when whole", () => {
    expect([0, 2, 2.5].map(usdTick)).toEqual(["$0", "$2", "$2.50"]);
  });

  it("writes billions bare when whole and keeps the half of a $2.5B step", () => {
    expect([0, 2.5e9, 5e9, 7.5e9, 10e9].map(usdBillionsTick)).toEqual(["$0", "$2.5B", "$5B", "$7.5B", "$10B"]);
    expect([100e9, 200e9].map(usdBillionsTick)).toEqual(["$100B", "$200B"]);
    expect([0.25e9, 0.5e9, 0.75e9].map(usdBillionsTick)).toEqual(["$0.25B", "$0.5B", "$0.75B"]);
  });
});
