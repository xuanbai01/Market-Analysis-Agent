/**
 * featured-claim — picks the "headline" Claim per section so the
 * frontend can render a SectionChart at the top of each card. Phase
 * 3.3.B.
 *
 * The hard part of 3.3.B is matching frontend logic to backend keys
 * without surfacing those keys in the schema. We match on
 * ``Claim.description`` (defined in each tool service's
 * ``_DESCRIPTIONS`` dict and stable across tool revisions). These
 * tests pin the descriptions we expect; if a backend rename ships
 * without a matching frontend update, these fail loudly here rather
 * than silently in production with a missing chart.
 *
 * Coverage:
 *
 * 1. **Earnings** picks both eps_actual + eps_estimate (dual-line).
 * 2. **Quality** picks ROE.
 * 3. **Capital Allocation** picks CapEx per share.
 * 4. **Macro** uses a description-suffix predicate (the descriptions
 *    are dynamic — ``f"{label} (latest observation)"``).
 * 5. **Valuation / Peers / Risk Factors / unknown title** — null.
 * 6. Sparse history (length < 2) on the matched claim — null.
 * 7. Description matching is **exact**, not substring (so "Operating
 *    margin" doesn't accidentally match "Operating margin TTM").
 */
import { describe, expect, it } from "vitest";

import type { Claim, ClaimHistoryPoint, Section } from "./schemas";
import { featuredClaim } from "./featured-claim";

function makeHistory(values: number[]): ClaimHistoryPoint[] {
  return values.map((v, i) => ({ period: `2024-Q${i + 1}`, value: v }));
}

function claim(
  description: string,
  value: number | null,
  history: ClaimHistoryPoint[] = [],
): Claim {
  return {
    description,
    value,
    source: {
      tool: "yfinance.fundamentals",
      fetched_at: "2026-04-29T14:00:00+00:00",
    },
    history,
  };
}

function section(title: string, claims: Claim[]): Section {
  return { title, claims, summary: "", confidence: "high" };
}

// ── Earnings ─────────────────────────────────────────────────────────

describe("featuredClaim — Earnings", () => {
  it("picks eps_actual as primary and eps_estimate as secondary", () => {
    const sec = section("Earnings", [
      claim("Most recent earnings report date", "2024-10-31"),
      claim("Reported EPS (latest quarter)", 2.18, makeHistory([1.4, 1.53, 2.05, 2.18])),
      claim(
        "Consensus EPS estimate (latest quarter, going in)",
        2.1,
        makeHistory([1.35, 1.5, 2.0, 2.1]),
      ),
      claim("EPS surprise % (latest quarter)", 3.8, makeHistory([3.7, 2.0, 2.5, 3.8])),
    ]);

    const result = featuredClaim(sec);

    expect(result).not.toBeNull();
    expect(result?.primary.description).toBe("Reported EPS (latest quarter)");
    expect(result?.secondary?.description).toBe(
      "Consensus EPS estimate (latest quarter, going in)",
    );
  });

  it("returns null when EPS history is empty (graceful degrade)", () => {
    const sec = section("Earnings", [
      claim("Reported EPS (latest quarter)", 2.18, []), // no history
      claim("Consensus EPS estimate (latest quarter, going in)", 2.1, []),
    ]);
    expect(featuredClaim(sec)).toBeNull();
  });

  it("returns primary-only when secondary (estimate) is missing", () => {
    const sec = section("Earnings", [
      claim("Reported EPS (latest quarter)", 2.18, makeHistory([1.4, 2.18])),
    ]);
    const result = featuredClaim(sec);
    expect(result?.primary.description).toBe("Reported EPS (latest quarter)");
    expect(result?.secondary).toBeUndefined();
  });
});

// ── Quality ──────────────────────────────────────────────────────────

describe("featuredClaim — Quality", () => {
  it("picks Return on equity", () => {
    const sec = section("Quality", [
      claim("Return on equity", 0.18, makeHistory([0.15, 0.16, 0.17, 0.18])),
      claim("Gross margin", 0.46, makeHistory([0.43, 0.44, 0.45, 0.46])),
      claim("Operating margin", 0.32, makeHistory([0.29, 0.3, 0.31, 0.32])),
    ]);

    const result = featuredClaim(sec);
    expect(result?.primary.description).toBe("Return on equity");
    expect(result?.secondary).toBeUndefined();
  });

  it("returns null when ROE has no history", () => {
    // Pre-3.2.D cached report — ROE was a snapshot only.
    const sec = section("Quality", [
      claim("Return on equity", 0.18, []),
      claim("Gross margin", 0.46, makeHistory([0.43, 0.46])),
    ]);
    // We do NOT fall back to gross_margin; the picks are deliberate.
    // Better to render no chart than the wrong chart.
    expect(featuredClaim(sec)).toBeNull();
  });
});

// ── Capital Allocation ───────────────────────────────────────────────

describe("featuredClaim — Capital Allocation", () => {
  it("picks Capital expenditure per share", () => {
    const sec = section("Capital Allocation", [
      claim("Forward dividend yield", 0.005),
      claim("Buyback yield (latest fiscal year)", 0.04),
      claim(
        "Capital expenditure per share",
        2.5,
        makeHistory([1.8, 2.0, 2.2, 2.5]),
      ),
      claim(
        "Stock-based compensation per share",
        1.2,
        makeHistory([1.0, 1.1, 1.15, 1.2]),
      ),
    ]);

    const result = featuredClaim(sec);
    expect(result?.primary.description).toBe("Capital expenditure per share");
  });
});

// ── Macro (dynamic descriptions) ─────────────────────────────────────

describe("featuredClaim — Macro", () => {
  it("picks the first claim with description suffix '(latest observation)' that has history", () => {
    const sec = section("Macro", [
      claim("Resolved sector for macro context", "megacap_tech"),
      claim("FRED series chosen for this sector", "DGS10, MANEMP"),
      claim(
        "10-Year Treasury Constant Maturity Rate (latest observation)",
        4.32,
        makeHistory([4.1, 4.2, 4.25, 4.32]),
      ),
      claim(
        "Manufacturing employees (latest observation)",
        12_500_000,
        makeHistory([12_400_000, 12_450_000, 12_480_000, 12_500_000]),
      ),
      claim(
        "Human-readable label for FRED series DGS10",
        "10-Year Treasury Constant Maturity Rate",
      ),
    ]);

    const result = featuredClaim(sec);
    expect(result?.primary.description).toBe(
      "10-Year Treasury Constant Maturity Rate (latest observation)",
    );
    // Macro is single-line; secondary always undefined.
    expect(result?.secondary).toBeUndefined();
  });

  it("skips '(latest observation)' claims that have no history", () => {
    // FRED_API_KEY unset path: the .value claim is present but
    // history is empty.
    const sec = section("Macro", [
      claim(
        "10-Year Treasury Constant Maturity Rate (latest observation)",
        null,
        [],
      ),
      claim(
        "Manufacturing employees (latest observation)",
        12_500_000,
        makeHistory([12_400_000, 12_500_000]),
      ),
    ]);
    const result = featuredClaim(sec);
    expect(result?.primary.description).toBe(
      "Manufacturing employees (latest observation)",
    );
  });

  it("returns null when no '(latest observation)' claim has history", () => {
    const sec = section("Macro", [
      claim("Resolved sector for macro context", "unknown"),
      claim("10-Year Treasury Constant Maturity Rate (latest observation)", null, []),
    ]);
    expect(featuredClaim(sec)).toBeNull();
  });
});

// ── Sections without a featured claim ────────────────────────────────

describe("featuredClaim — sections that skip", () => {
  it("returns null for Valuation (no history-bearing claims today)", () => {
    const sec = section("Valuation", [
      claim("P/E ratio (trailing 12 months)", 28.5),
      claim("PEG ratio (P/E to growth, trailing)", 1.8),
    ]);
    expect(featuredClaim(sec)).toBeNull();
  });

  it("returns null for Peers (rendered via PeerScatter in 3.3.C)", () => {
    const sec = section("Peers", [claim("Peer 1 ticker", "MSFT")]);
    expect(featuredClaim(sec)).toBeNull();
  });

  it("returns null for Risk Factors (counts not series)", () => {
    const sec = section("Risk Factors", [
      claim("Newly added risk paragraphs vs prior 10-K", 3),
      claim("Risk paragraphs dropped vs prior 10-K", 1),
    ]);
    expect(featuredClaim(sec)).toBeNull();
  });

  it("returns null for an unknown section title", () => {
    const sec = section("Crypto Outlook", [
      claim("Reported EPS (latest quarter)", 2.18, makeHistory([1.4, 2.18])),
    ]);
    // Even if a description happens to match, an unknown section is a
    // signal the data shape changed; opt out rather than guess.
    expect(featuredClaim(sec)).toBeNull();
  });
});

// ── Matching strictness ──────────────────────────────────────────────

describe("featuredClaim — matching is exact, not substring", () => {
  it("does not match a description that's a superset of the canonical one", () => {
    // Hypothetical: backend ships "Operating margin TTM" — the spec
    // for Quality is "Return on equity", and even if it were
    // "Operating margin", the matcher must be exact so a typo or
    // suffix-creep doesn't silently match.
    const sec = section("Quality", [
      claim(
        "Return on equity (TTM, weighted)", // superset of canonical
        0.18,
        makeHistory([0.15, 0.18]),
      ),
    ]);
    expect(featuredClaim(sec)).toBeNull();
  });

  it("does not match a description that's a substring of the canonical one", () => {
    const sec = section("Quality", [
      claim(
        "Return on", // truncated
        0.18,
        makeHistory([0.15, 0.18]),
      ),
    ]);
    expect(featuredClaim(sec)).toBeNull();
  });
});
