import { describe, expect, it } from "vitest";

import { RAW_OPTIONS_REPORT } from "../components/options/fixture";
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

  it("reads a symbol with no options", () => {
    const report = OptionsReportSchema.parse({
      ...RAW_OPTIONS_REPORT,
      status: "no_options",
      spot: null,
      expiries: [],
      chain: null,
      earnings: null,
      claims: [],
    });
    expect(report.status).toBe("no_options");
    expect(report.chain).toBeNull();
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
