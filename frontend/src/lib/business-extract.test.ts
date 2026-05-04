/**
 * business-extract tests (Phase 4.4.A).
 *
 * Pulls the Business section's claims into the shape ``BusinessCard``
 * renders. Description matches mirror the backend's
 * ``app/services/business_info.py`` constants — pin them so a backend
 * rename fails this suite loudly.
 */
import { describe, expect, it } from "vitest";

import { extractBusinessInfo } from "./business-extract";
import type { Claim, ClaimValue, Section } from "./schemas";

function claim(description: string, value: ClaimValue): Claim {
  return {
    description,
    value,
    source: { tool: "yfinance.business_info", fetched_at: "2026-05-04T01:00:00+00:00" },
    history: [],
  };
}

function section(claims: Claim[]): Section {
  return { title: "Business", claims, summary: "", confidence: "medium" };
}

describe("extractBusinessInfo", () => {
  it("returns the three fields when all three claims are present", () => {
    const out = extractBusinessInfo(
      section([
        claim(
          "Business description (from 10-K filing)",
          "Apple Inc. designs, manufactures, and markets smartphones.",
        ),
        claim("Headquarters location", "Cupertino, CA, United States"),
        claim("Full-time employee count", 164_000),
      ]),
    );
    expect(out).toEqual({
      summary: expect.stringContaining("Apple Inc."),
      hq: "Cupertino, CA, United States",
      employeeCount: 164_000,
    });
  });

  it("returns nulls for missing claims rather than throwing", () => {
    const out = extractBusinessInfo(section([]));
    expect(out).toEqual({
      summary: null,
      hq: null,
      employeeCount: null,
    });
  });

  it("rejects non-string summary / non-string hq / non-numeric employees", () => {
    const out = extractBusinessInfo(
      section([
        claim("Business description (from 10-K filing)", 42 as unknown as ClaimValue),
        claim("Headquarters location", null),
        claim("Full-time employee count", "164000"),
      ]),
    );
    expect(out).toEqual({
      summary: null,
      hq: null,
      employeeCount: null,
    });
  });
});
