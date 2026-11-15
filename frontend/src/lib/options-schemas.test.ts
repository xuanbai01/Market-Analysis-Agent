import { describe, expect, it } from "vitest";

import { RAW_NO_OPTIONS_REPORT, RAW_OPTIONS_READ, RAW_OPTIONS_REPORT } from "../components/options/fixture";
import { ExpiryChainSchema, OptionsReadSchema, OptionsReportSchema } from "./options-schemas";

describe("OptionsReportSchema", () => {
  it("parses a report the backend built (the contract)", () => {
    const report = OptionsReportSchema.parse(RAW_OPTIONS_REPORT);
    expect(report.symbol).toBe("NVDA");
    expect(report.status).toBe("ok");
    expect(report.expiries.length).toBeGreaterThan(3);
    expect(report.chain?.rows.length).toBeGreaterThan(0);
    expect(report.earnings?.next_timing).toBe("after_close");
    expect(report.earnings?.implied_move).toBeGreaterThan(0);
    expect(report.history.percentile).not.toBeNull();
    expect(report.claims.length).toBeGreaterThan(0);
  });

  it("reads a symbol with no options, as the backend sends it", () => {
    const report = OptionsReportSchema.parse(RAW_NO_OPTIONS_REPORT);
    expect(report.status).toBe("no_options");
    expect(report.chain).toBeNull();
    expect(report.history.sessions).toBe(0);
  });

  it("says whether the quotes are the close's, and assumes not when a server doesn't say", () => {
    expect(OptionsReportSchema.parse(RAW_OPTIONS_REPORT).at_close).toBe(true);
    const { at_close: _omitted, ...older } = RAW_OPTIONS_REPORT;
    expect(OptionsReportSchema.parse(older).at_close).toBe(false);
  });

  it("tolerates fields the backend adds later and an unknown timing", () => {
    const raw = {
      ...RAW_OPTIONS_REPORT,
      something_new: 1,
      earnings: { ...RAW_OPTIONS_REPORT.earnings, next_timing: "overnight" },
    };
    const report = OptionsReportSchema.parse(raw);
    expect(report.earnings?.next_timing).toBe("unknown");
  });

  it("parses one expiry's chain", () => {
    const chain = ExpiryChainSchema.parse(RAW_OPTIONS_REPORT.chain);
    expect(chain.expiry).toBe(RAW_OPTIONS_REPORT.chain.expiry);
  });
});

describe("a report with a refused earnings move", () => {
  it("parses the refusal, a claim whose value is its reason", () => {
    const refusal = {
      description: "Implied earnings move, report on 2027-02-09: not priced",
      value: "the first expiry after the report is 98 days out",
      unit: "string",
      source: { tool: "computed.options", fetched_at: "2026-11-15T05:37:50Z", url: null, detail: "why" },
    };
    const report = OptionsReportSchema.parse({ ...RAW_OPTIONS_REPORT, claims: [...RAW_OPTIONS_REPORT.claims, refusal] });
    expect(report.claims.at(-1)?.value).toBe("the first expiry after the report is 98 days out");
  });
});

describe("OptionsReadSchema", () => {
  it("refuses a read that lost its points or claims", () => {
    const { points: _p, ...noPoints } = RAW_OPTIONS_READ;
    const { claims: _c, ...noClaims } = RAW_OPTIONS_READ;
    expect(OptionsReadSchema.safeParse(noPoints).success).toBe(false);
    expect(OptionsReadSchema.safeParse(noClaims).success).toBe(false);
  });

  it("parses a cited read with its own claims", () => {
    const read = OptionsReadSchema.parse(RAW_OPTIONS_READ);
    expect(read.points).toHaveLength(2);
    expect(read.points[0].claim_refs[1]).toEqual({ section: "Options", index: 2 });
    expect(read.claims[read.points[1].claim_refs[0].index].unit).toBe("fraction");
  });
});
