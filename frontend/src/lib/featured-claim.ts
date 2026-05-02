/**
 * featured-claim — picks the "headline" Claim per section so the
 * frontend can render a SectionChart at the top of each card. Phase
 * 3.3.B.
 *
 * ## Why match by description, not by claim key
 *
 * The Pydantic schema flattens ``dict[str, Claim]`` into
 * ``Section.claims: list[Claim]`` and the stable backend keys
 * (``eps_actual``, ``roe``, ``capex_per_share``, …) don't survive the
 * round-trip. We match on ``Claim.description`` instead — the strings
 * are defined in each tool's ``_DESCRIPTIONS`` dict and only change on
 * a deliberate rename. The integration tests in this module assert the
 * exact descriptions; a backend rename without a matching frontend
 * update breaks the test, not production rendering.
 *
 * Adding a ``Claim.key`` field to the schema would be cleaner but
 * touches backend + cached JSONB rows + Zod + tests for what is, today,
 * a 4-section matching problem. Revisit if 3.3.C / 3.4 also want it.
 *
 * ## Section picks (rationale per section in the README of this PR)
 *
 * | Section            | Primary description                                  | Secondary                                          |
 * |--------------------|------------------------------------------------------|----------------------------------------------------|
 * | Earnings           | "Reported EPS (latest quarter)"                      | "Consensus EPS estimate (latest quarter, going in)" |
 * | Quality            | "Return on equity"                                   | —                                                  |
 * | Capital Allocation | "Capital expenditure per share"                      | —                                                  |
 * | Macro              | first claim ending in "(latest observation)"        | —                                                  |
 * | Valuation, Peers, Risk Factors, others             | (no spec — render no chart) | —                              |
 *
 * Macro is the odd one out because its descriptions are dynamic
 * (``f"{label} (latest observation)"`` per FRED series). We use a
 * suffix predicate instead of an exact match.
 */
import type { Claim, Section } from "./schemas";

export interface FeaturedClaimResult {
  primary: Claim;
  secondary?: Claim;
}

interface FeaturedSpec {
  /**
   * Pick the primary Claim from ``section.claims``. Return undefined
   * to signal "no headline metric available".
   */
  primary: (claims: readonly Claim[]) => Claim | undefined;
  /** Optional secondary Claim for dual-line charts (Earnings only today). */
  secondary?: (claims: readonly Claim[]) => Claim | undefined;
}

/** Strict equality on description — anti-substring, anti-typo. */
function exact(target: string) {
  return (claims: readonly Claim[]): Claim | undefined =>
    claims.find((c) => c.description === target);
}

/** Match ``description.endsWith(suffix)`` AND has 2+ history points. */
function endsWithAndHasHistory(suffix: string) {
  return (claims: readonly Claim[]): Claim | undefined =>
    claims.find(
      (c) => c.description.endsWith(suffix) && c.history.length >= 2,
    );
}

const SPECS: Record<string, FeaturedSpec> = {
  Earnings: {
    primary: exact("Reported EPS (latest quarter)"),
    secondary: exact("Consensus EPS estimate (latest quarter, going in)"),
  },
  Quality: {
    primary: exact("Return on equity"),
  },
  "Capital Allocation": {
    primary: exact("Capital expenditure per share"),
  },
  Macro: {
    // Macro descriptions are dynamic per FRED series; suffix-match.
    // The history.length check is folded into the predicate so we
    // skip a series that has the right description shape but no data
    // (e.g. FRED_API_KEY unset).
    primary: endsWithAndHasHistory("(latest observation)"),
  },
};

/**
 * Resolve the section's headline Claim(s), or null when the section
 * has no spec, no matching claim, or the matched claim's history is
 * too short to chart.
 */
export function featuredClaim(section: Section): FeaturedClaimResult | null {
  const spec = SPECS[section.title];
  if (!spec) return null;

  const primary = spec.primary(section.claims);
  if (!primary) return null;
  if (primary.history.length < 2) return null;

  const secondary = spec.secondary?.(section.claims);
  // Don't propagate a secondary that's missing or sparse — the chart
  // gracefully degrades to single-line rather than rendering a stub
  // estimate line over a single point.
  if (secondary && secondary.history.length >= 2) {
    return { primary, secondary };
  }
  return { primary };
}
