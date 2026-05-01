/**
 * Schema-shape tests. The point isn't to exhaustively test Zod — Zod
 * tests itself. The point is to lock in the contract with the backend
 * so that if a Pydantic field renames, our parse fails here in one
 * place.
 *
 * These shapes are copy-pasted from realistic backend responses
 * (taken from a live ``POST /v1/research/AAPL`` round-trip during
 * dogfooding). If you regenerate, regenerate from a real response.
 */
import { describe, it, expect } from "vitest";
import {
  ClaimHistoryPointSchema,
  ClaimSchema,
  ResearchReportSchema,
  ResearchReportSummariesSchema,
  ResearchReportSummarySchema,
} from "./schemas";

describe("ResearchReportSchema", () => {
  it("parses a minimal but realistic report", () => {
    const payload = {
      symbol: "AAPL",
      generated_at: "2026-04-29T14:05:00+00:00",
      sections: [
        {
          title: "Valuation",
          claims: [
            {
              description: "Trailing P/E",
              value: 28.5,
              source: {
                tool: "yfinance.fundamentals",
                fetched_at: "2026-04-29T14:00:00+00:00",
                url: "https://finance.yahoo.com/quote/AAPL",
                detail: "Ticker.info[trailingPE]",
              },
            },
          ],
          summary: "Trades at 28.5x trailing earnings.",
          confidence: "high",
        },
      ],
      overall_confidence: "high",
      tool_calls_audit: ["fetch_fundamentals: ok"],
    };

    const parsed = ResearchReportSchema.parse(payload);

    expect(parsed.symbol).toBe("AAPL");
    expect(parsed.sections).toHaveLength(1);
    expect(parsed.sections[0].claims[0].value).toBe(28.5);
    expect(parsed.sections[0].claims[0].source.url).toBe(
      "https://finance.yahoo.com/quote/AAPL",
    );
  });

  it("accepts a null claim value (e.g. 'data unavailable')", () => {
    const payload = {
      symbol: "AAPL",
      generated_at: "2026-04-29T14:05:00+00:00",
      sections: [
        {
          title: "Quality",
          claims: [
            {
              description: "ROIC",
              value: null,
              source: {
                tool: "yfinance.fundamentals",
                fetched_at: "2026-04-29T14:00:00+00:00",
              },
            },
          ],
          summary: "",
          confidence: "low",
        },
      ],
      overall_confidence: "low",
      tool_calls_audit: [],
    };
    expect(() => ResearchReportSchema.parse(payload)).not.toThrow();
  });

  it("accepts a string claim value (e.g. a date or qualitative note)", () => {
    const payload = {
      symbol: "AAPL",
      generated_at: "2026-04-29T14:05:00+00:00",
      sections: [
        {
          title: "Earnings",
          claims: [
            {
              description: "Next reporting date",
              value: "2026-05-01",
              source: {
                tool: "yfinance.earnings",
                fetched_at: "2026-04-29T14:00:00+00:00",
              },
            },
          ],
          summary: "",
          confidence: "medium",
        },
      ],
      overall_confidence: "medium",
      tool_calls_audit: [],
    };
    expect(() => ResearchReportSchema.parse(payload)).not.toThrow();
  });

  it("rejects an unknown confidence level", () => {
    const payload = {
      symbol: "AAPL",
      generated_at: "2026-04-29T14:05:00+00:00",
      sections: [],
      overall_confidence: "uncertain", // not one of high/medium/low
      tool_calls_audit: [],
    };
    expect(() => ResearchReportSchema.parse(payload)).toThrow();
  });
});

describe("ResearchReportSummarySchema", () => {
  it("parses a sidebar-shaped row", () => {
    const payload = {
      symbol: "AAPL",
      focus: "full",
      report_date: "2026-04-29",
      generated_at: "2026-04-29T14:05:00+00:00",
      overall_confidence: "high",
    };

    const parsed = ResearchReportSummarySchema.parse(payload);
    expect(parsed.symbol).toBe("AAPL");
    expect(parsed.report_date).toBe("2026-04-29");
  });

  it("rejects a bad date shape (full ISO instead of YYYY-MM-DD)", () => {
    const payload = {
      symbol: "AAPL",
      focus: "full",
      report_date: "2026-04-29T14:05:00+00:00",
      generated_at: "2026-04-29T14:05:00+00:00",
      overall_confidence: "high",
    };
    expect(() => ResearchReportSummarySchema.parse(payload)).toThrow();
  });

  it("array form parses an empty list", () => {
    expect(ResearchReportSummariesSchema.parse([])).toEqual([]);
  });
});

// ── Phase 3.1: Claim.history ─────────────────────────────────────────

describe("ClaimHistoryPointSchema", () => {
  it("parses a quarterly point", () => {
    const p = ClaimHistoryPointSchema.parse({
      period: "2024-Q4",
      value: 2.18,
    });
    expect(p.period).toBe("2024-Q4");
    expect(p.value).toBe(2.18);
  });

  it("rejects a non-numeric value (only floats sparkline)", () => {
    expect(() =>
      ClaimHistoryPointSchema.parse({ period: "2024-Q4", value: "2.18" }),
    ).toThrow();
  });

  it("rejects an empty period label", () => {
    expect(() =>
      ClaimHistoryPointSchema.parse({ period: "", value: 2.18 }),
    ).toThrow();
  });
});

describe("ClaimSchema with history", () => {
  const validSource = {
    tool: "yfinance.fundamentals",
    fetched_at: "2026-04-29T14:00:00+00:00",
  };

  it("parses a claim with populated history", () => {
    const claim = ClaimSchema.parse({
      description: "EPS",
      value: 2.18,
      source: validSource,
      history: [
        { period: "2024-Q3", value: 2.05 },
        { period: "2024-Q4", value: 2.18 },
      ],
    });
    expect(claim.history).toHaveLength(2);
    expect(claim.history[0].period).toBe("2024-Q3");
    expect(claim.history[1].value).toBe(2.18);
  });

  it("defaults history to [] when the field is missing", () => {
    // Backwards-compat: a Claim payload from before Phase 3.1 has no
    // ``history`` key. Zod fills in the default so the renderer can
    // always read ``claim.history`` without optional-chaining.
    const claim = ClaimSchema.parse({
      description: "P/E",
      value: 28.5,
      source: validSource,
    });
    expect(claim.history).toEqual([]);
  });

  it("rejects a history with a non-numeric value", () => {
    expect(() =>
      ClaimSchema.parse({
        description: "EPS",
        value: 2.18,
        source: validSource,
        history: [{ period: "2024-Q4", value: "two-eighteen" }],
      }),
    ).toThrow();
  });
});
