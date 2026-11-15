import { describe, expect, it } from "vitest";

import { LENS } from "../components/lens/fixture";
import {
  billionTickLabels,
  companiesInYear,
  companyColor,
  firstReported,
  LENS_COLORS,
  pct,
  percentTickLabels,
  usdBillions,
} from "./lens";

describe("lens helpers", () => {
  it("keeps a company's color by its lens position, not its rank", () => {
    expect(companyColor(0)).toBe(LENS_COLORS[0]);
    expect(companyColor(7)).toBe(LENS_COLORS[0]);
    const rows = companiesInYear(LENS, 2025);
    expect(rows.map((r) => r.ticker)).toEqual(["AAA", "CCC", "BBB"]); // ranked by intensity
    expect(rows.find((r) => r.ticker === "CCC")?.color).toBe(LENS_COLORS[2]);
  });

  it("puts companies that did not report a year last", () => {
    const rows = companiesInYear(LENS, 2023);
    expect(rows[rows.length - 1]).toMatchObject({ ticker: "CCC", intensity: null });
  });

  it("finds the first year a company reported", () => {
    expect(firstReported(LENS.companies[2], LENS.years)).toEqual({ year: 2024, intensity: 0.1 });
  });

  it("formats dollars in billions and fractions in percent", () => {
    expect(usdBillions(384.79e9)).toBe("$384.8B");
    expect(usdBillions(740e6)).toBe("$740M");
    expect(pct(0.18388)).toBe("18.4%");
  });
});

describe("axis tick labels", () => {
  it("writes whole-percent steps without decimals", () => {
    expect(percentTickLabels([0, 0.05, 0.1, 0.15])).toEqual(["0%", "5%", "10%", "15%"]);
  });

  it("gives every tick the decimals a fractional step needs", () => {
    // niceTicks steps by 2.5%: rounding read "0%, 3%, 5%, 8%" on the SBC lens.
    expect(percentTickLabels([0, 0.025, 0.05, 0.075, 0.1, 0.125])).toEqual([
      "0.0%",
      "2.5%",
      "5.0%",
      "7.5%",
      "10.0%",
      "12.5%",
    ]);
    expect(percentTickLabels([0, 0.0025, 0.005])).toEqual(["0.00%", "0.25%", "0.50%"]);
  });

  it("labels a single tick without decimals", () => {
    expect(percentTickLabels([0.1])).toEqual(["10%"]);
  });

  it("writes dollar ticks in billions with the decimals the step needs", () => {
    expect(billionTickLabels([0, 100e9, 200e9])).toEqual(["$0", "$100B", "$200B"]);
    expect(billionTickLabels([0, 2.5e9, 5e9, 7.5e9])).toEqual(["$0", "$2.5B", "$5.0B", "$7.5B"]);
  });
});
