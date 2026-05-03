/**
 * risk-extract tests (Phase 4.3.A).
 *
 * Pulls the 4 numeric Risk10KDiff claims out of the Risk Factors
 * section. Pre-4.3.B these are aggregate counts; 4.3.B will add
 * per-category bucketing via Haiku.
 *
 * Two helpers:
 *
 *   - extractRiskDiffBars(section) → { added, removed, kept, charDelta } | null
 *   - extractRiskDiffSummary(section) → { framing, netDelta }
 *       framing ∈ "expanded" | "shrank" | "stable"
 *       netDelta = added − removed (signed paragraph delta)
 *
 * Description matches mirror app/services/research_tool_registry.py
 * ::_build_risk_factors:
 *
 *   "Newly added risk paragraphs vs prior 10-K"
 *   "Risk paragraphs dropped vs prior 10-K"
 *   "Risk paragraphs kept (carryover)"
 *   "Item 1A char delta vs prior 10-K"
 */
import { describe, expect, it } from "vitest";

import {
  extractRiskDiffBars,
  extractRiskDiffSummary,
} from "./risk-extract";
import type { Claim, ClaimValue, Section } from "./schemas";

function claim(description: string, value: ClaimValue): Claim {
  return {
    description,
    value,
    source: { tool: "sec.ten_k_risks_diff", fetched_at: "2026-05-03T14:00:00+00:00" },
    history: [],
  };
}

function section(claims: Claim[]): Section {
  return { title: "Risk Factors", claims, summary: "", confidence: "high" };
}

const FULL: Claim[] = [
  claim("Newly added risk paragraphs vs prior 10-K", 12),
  claim("Risk paragraphs dropped vs prior 10-K", 3),
  claim("Risk paragraphs kept (carryover)", 47),
  claim("Item 1A char delta vs prior 10-K", 8421),
  claim("Business section length (chars)", 32100),
];

// ── extractRiskDiffBars ──────────────────────────────────────────────

describe("extractRiskDiffBars", () => {
  it("returns the 4 numeric fields when all 4 are present", () => {
    expect(extractRiskDiffBars(section(FULL))).toEqual({
      added: 12,
      removed: 3,
      kept: 47,
      charDelta: 8421,
    });
  });

  it("returns null when added or removed is missing (diff unavailable)", () => {
    expect(
      extractRiskDiffBars(
        section([claim("Risk paragraphs kept (carryover)", 47)]),
      ),
    ).toBeNull();
  });

  it("returns null when section has no claims (extraction failed upstream)", () => {
    expect(extractRiskDiffBars(section([]))).toBeNull();
  });

  it("supports negative char_delta (disclosure shrank)", () => {
    const bars = extractRiskDiffBars(
      section([
        claim("Newly added risk paragraphs vs prior 10-K", 1),
        claim("Risk paragraphs dropped vs prior 10-K", 5),
        claim("Risk paragraphs kept (carryover)", 50),
        claim("Item 1A char delta vs prior 10-K", -2400),
      ]),
    );
    expect(bars?.charDelta).toBe(-2400);
  });

  it("rejects non-numeric values for required fields", () => {
    expect(
      extractRiskDiffBars(
        section([
          claim("Newly added risk paragraphs vs prior 10-K", null),
          claim("Risk paragraphs dropped vs prior 10-K", 3),
          claim("Risk paragraphs kept (carryover)", 47),
          claim("Item 1A char delta vs prior 10-K", 0),
        ]),
      ),
    ).toBeNull();
  });
});

// ── extractRiskDiffSummary ──────────────────────────────────────────

describe("extractRiskDiffSummary", () => {
  it("returns 'expanded' when net delta > 0", () => {
    const out = extractRiskDiffSummary(section(FULL));
    expect(out?.framing).toBe("expanded");
    expect(out?.netDelta).toBe(9); // 12 added − 3 removed
  });

  it("returns 'shrank' when net delta < 0", () => {
    const out = extractRiskDiffSummary(
      section([
        claim("Newly added risk paragraphs vs prior 10-K", 1),
        claim("Risk paragraphs dropped vs prior 10-K", 5),
        claim("Risk paragraphs kept (carryover)", 50),
        claim("Item 1A char delta vs prior 10-K", -2400),
      ]),
    );
    expect(out?.framing).toBe("shrank");
    expect(out?.netDelta).toBe(-4);
  });

  it("returns 'stable' when net delta == 0", () => {
    const out = extractRiskDiffSummary(
      section([
        claim("Newly added risk paragraphs vs prior 10-K", 3),
        claim("Risk paragraphs dropped vs prior 10-K", 3),
        claim("Risk paragraphs kept (carryover)", 50),
        claim("Item 1A char delta vs prior 10-K", 100),
      ]),
    );
    expect(out?.framing).toBe("stable");
    expect(out?.netDelta).toBe(0);
  });

  it("returns null when underlying bars are unavailable", () => {
    expect(extractRiskDiffSummary(section([]))).toBeNull();
  });
});
