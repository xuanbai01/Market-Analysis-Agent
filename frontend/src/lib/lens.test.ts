import { describe, expect, it } from "vitest";

import { LENS } from "../components/lens/fixture";
import { companiesInYear, companyColor, firstReported, LENS_COLORS, pct, usdBillions } from "./lens";

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
