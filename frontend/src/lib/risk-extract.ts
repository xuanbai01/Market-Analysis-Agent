/**
 * risk-extract — pulls Risk Factors section claims into the shapes
 * the RiskDiffCard renders.
 *
 * Phase 4.3.A: aggregate paragraph counts (4 bars).
 * Phase 4.3.B: per-category paragraph deltas via Haiku classification
 *   (one bar per non-zero bucket). The card prefers the per-category
 *   shape when available and falls back to aggregates otherwise — pre-
 *   4.3.B cached rows continue to render.
 *
 * Helpers:
 *   - extractRiskDiffBars(section) → { added, removed, kept, charDelta } | null
 *   - extractRiskDiffSummary(section) → { framing, netDelta } | null
 *   - extractRiskCategoryDeltas(section) → RiskCategoryDelta[] | null
 *
 * Description matches mirror app/services/research_tool_registry.py
 * ::_build_risk_factors verbatim.
 */
import type { Claim, Section } from "./schemas";

const DESC_ADDED = "Newly added risk paragraphs vs prior 10-K";
const DESC_REMOVED = "Risk paragraphs dropped vs prior 10-K";
const DESC_KEPT = "Risk paragraphs kept (carryover)";
const DESC_CHAR_DELTA = "Item 1A char delta vs prior 10-K";

export interface RiskDiffBars {
  added: number;
  removed: number;
  kept: number;
  charDelta: number;
}

export type RiskDiffFraming = "expanded" | "shrank" | "stable";

export interface RiskDiffSummary {
  framing: RiskDiffFraming;
  netDelta: number;
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function findNumeric(
  claims: readonly Claim[],
  description: string,
): number | null {
  const claim = claims.find((c) => c.description === description);
  if (!claim || !isFiniteNumber(claim.value)) return null;
  return claim.value;
}

/**
 * Returns the 4 numeric fields when all four claims are present and
 * numeric. Returns null when any required field is missing — the card
 * degrades to the "risk diff unavailable" fallback in that case.
 */
export function extractRiskDiffBars(section: Section): RiskDiffBars | null {
  const added = findNumeric(section.claims, DESC_ADDED);
  const removed = findNumeric(section.claims, DESC_REMOVED);
  const kept = findNumeric(section.claims, DESC_KEPT);
  const charDelta = findNumeric(section.claims, DESC_CHAR_DELTA);
  if (
    added === null ||
    removed === null ||
    kept === null ||
    charDelta === null
  ) {
    return null;
  }
  return { added, removed, kept, charDelta };
}

/**
 * Derives the prose summary's framing word from the bars. Returns null
 * when bars themselves are unavailable.
 */
export function extractRiskDiffSummary(
  section: Section,
): RiskDiffSummary | null {
  const bars = extractRiskDiffBars(section);
  if (!bars) return null;
  const netDelta = bars.added - bars.removed;
  let framing: RiskDiffFraming;
  if (netDelta > 0) framing = "expanded";
  else if (netDelta < 0) framing = "shrank";
  else framing = "stable";
  return { framing, netDelta };
}
