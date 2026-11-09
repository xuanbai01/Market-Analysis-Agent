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

// Phase 4.3.B — RiskCategory mirror of the backend enum in
// ``app/schemas/ten_k.py::RiskCategory``. Kept as a local TS union so
// callers don't need to import from schemas.ts (the value isn't
// surfaced as a typed Claim field — it's encoded into the Claim
// description string by the backend's _build_risk_factors).
export type RiskCategory =
  | "ai_regulatory"
  | "export_controls"
  | "supply_concentration"
  | "customer_concentration"
  | "competition"
  | "cybersecurity"
  | "ip"
  | "macro"
  | "other";

// Human-readable label per category, mirroring the backend's
// ``_RISK_CATEGORY_LABELS`` in research_tool_registry.py. Drives both
// the description-string match (label → category lookup) and the
// rendered chip text on the card.
const RISK_CATEGORY_LABELS: Record<RiskCategory, string> = {
  ai_regulatory: "AI / regulatory",
  export_controls: "Export controls",
  supply_concentration: "Supply concentration",
  customer_concentration: "Customer concentration",
  competition: "Competition",
  cybersecurity: "Cybersecurity",
  ip: "IP",
  macro: "Macro",
  other: "Other",
};

// Reverse lookup: human label → enum key. Built once at module load.
const LABEL_TO_CATEGORY: Map<string, RiskCategory> = new Map(
  (Object.entries(RISK_CATEGORY_LABELS) as [RiskCategory, string][]).map(
    ([cat, label]) => [label, cat],
  ),
);

const CATEGORY_DESC_SUFFIX = " risk paragraph delta vs prior 10-K";

export interface RiskDiffBars {
  added: number;
  removed: number;
  kept: number;
  charDelta: number;
}

export type RiskDiffFraming = "expanded" | "shrank" | "reworked" | "stable";

/** Net change, as a share of the prior 10-K's paragraphs, that counts
 *  as the disclosure growing or shrinking. Below it the length is
 *  "about the same" — KO's +3 of 259 used to read "Disclosure
 *  expanded" beside an LLM line saying "churned, not expanded". */
export const RISK_NET_CHANGE_THRESHOLD = 0.05;
/** Added + dropped, as a share of the prior paragraphs, that makes a
 *  same-length disclosure "reworked" rather than "stable". */
export const RISK_CHURN_THRESHOLD = 0.1;

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

export interface RiskCategoryDelta {
  category: RiskCategory;
  /** Human-readable label matching the chip text on the card. */
  label: string;
  /** Net paragraph delta (added − removed). Never zero — the
   *  categorizer drops zero-net buckets before the claim is emitted. */
  delta: number;
}

/**
 * Phase 4.3.B — collects per-category paragraph deltas surfaced as
 * Claims with description ``"<Label> risk paragraph delta vs prior
 * 10-K"``. Returns ``null`` when no such claims are present (pre-4.3.B
 * cached reports + stable disclosures), letting the card fall back to
 * the aggregate 4-bar chart.
 *
 * Sorted by absolute delta descending so the highest-signal buckets
 * render first. Non-numeric values are dropped silently — corrupt
 * claim values shouldn't crash the card.
 */
export function extractRiskCategoryDeltas(
  section: Section,
): RiskCategoryDelta[] | null {
  const out: RiskCategoryDelta[] = [];
  for (const claim of section.claims) {
    if (!claim.description.endsWith(CATEGORY_DESC_SUFFIX)) continue;
    if (!isFiniteNumber(claim.value)) continue;
    const label = claim.description.slice(
      0,
      claim.description.length - CATEGORY_DESC_SUFFIX.length,
    );
    const category = LABEL_TO_CATEGORY.get(label);
    if (!category) continue;
    out.push({ category, label, delta: claim.value });
  }
  if (out.length === 0) return null;
  out.sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta));
  return out;
}

/**
 * Derives the summary's framing word from the bars, sized against the
 * prior 10-K (kept + dropped paragraphs): a net change of 5% or more is
 * "expanded" / "shrank"; otherwise 10%+ churn is "reworked", and less
 * is "stable". Returns null when the bars are unavailable.
 */
export function extractRiskDiffSummary(
  section: Section,
): RiskDiffSummary | null {
  const bars = extractRiskDiffBars(section);
  if (!bars) return null;
  const netDelta = bars.added - bars.removed;
  const prior = Math.max(1, bars.kept + bars.removed);
  let framing: RiskDiffFraming;
  if (Math.abs(netDelta) / prior >= RISK_NET_CHANGE_THRESHOLD) {
    framing = netDelta > 0 ? "expanded" : "shrank";
  } else if ((bars.added + bars.removed) / prior >= RISK_CHURN_THRESHOLD) {
    framing = "reworked";
  } else {
    framing = "stable";
  }
  return { framing, netDelta };
}
