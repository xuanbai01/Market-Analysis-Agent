import { describe, expect, it } from "vitest";

import { RAW_NO_OPTIONS_REPORT, RAW_OPTIONS_REPORT } from "../components/options/fixture";
import { ExpiryChainSchema, OptionsReportSchema } from "./options-schemas";

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
