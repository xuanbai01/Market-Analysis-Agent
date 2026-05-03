/**
 * growth-extract — pulls 5 per-share growth series from the Quality
 * section, rebases each to its first history point = 100 so the
 * resulting MultiLine shows true relative growth on a shared axis.
 *
 * Phase 4.3.A.
 *
 * Two helpers:
 *
 *   - extractGrowthSeries(section)      → MultiLineSeries[] (rebased)
 *   - extractGrowthMultipliers(section) → { rev, gp, opi, fcf, ocf }
 *                                         where each = latest / first.
 *
 * Description matches mirror app/services/fundamentals.py::_DESCRIPTIONS.
 * Tests pin them so a backend rename fails the suite loudly.
 */
import type { Claim, ClaimHistoryPoint, Section } from "./schemas";
import type { MultiLineSeries } from "../components/MultiLine";

const DESC_REVENUE = "Revenue per share";
const DESC_GP = "Gross profit per share";
const DESC_OPI = "Operating income per share";
const DESC_FCF = "Free cash flow per share";
const DESC_OCF = "Operating cash flow per share";

// Strata accent colors — locked to backend metric categories.
const COLOR_VAL = "#6cb6ff";
const COLOR_QUAL = "#7ad0a6";
const COLOR_CASH = "#e8c277";
const COLOR_EARN = "#d68dc6";
const COLOR_DIM = "#8892a0";

const SERIES_SPEC: { description: string; label: string; color: string }[] = [
  { description: DESC_REVENUE, label: "Revenue", color: COLOR_VAL },
  { description: DESC_GP, label: "Gross profit", color: COLOR_QUAL },
  { description: DESC_OPI, label: "Op income", color: COLOR_CASH },
  { description: DESC_FCF, label: "FCF", color: COLOR_EARN },
  { description: DESC_OCF, label: "OCF", color: COLOR_DIM },
];

export interface GrowthMultipliers {
  rev: number | null;
  gp: number | null;
  opi: number | null;
  fcf: number | null;
  ocf: number | null;
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function findClaim(
  claims: readonly Claim[],
  description: string,
): Claim | undefined {
  return claims.find((c) => c.description === description);
}

/**
 * Rebase a history series so the first point equals 100. Returns null
 * when the history is empty or the first value is zero (can't divide).
 */
function rebaseHistory(
  history: readonly ClaimHistoryPoint[],
): ClaimHistoryPoint[] | null {
  if (history.length === 0) return null;
  const base = history[0].value;
  if (!isFiniteNumber(base) || base === 0) return null;
  return history.map((p) => ({
    period: p.period,
    value: (p.value / base) * 100,
  }));
}

/**
 * Returns 5 MultiLineSeries for the per-share growth chart, each
 * rebased to its own first-point = 100. Series whose history is empty
 * or whose first value is zero are dropped.
 */
export function extractGrowthSeries(section: Section): MultiLineSeries[] {
  const out: MultiLineSeries[] = [];
  for (const spec of SERIES_SPEC) {
    const claim = findClaim(section.claims, spec.description);
    if (!claim) continue;
    const rebased = rebaseHistory(claim.history);
    if (!rebased) continue;
    out.push({ label: spec.label, color: spec.color, history: rebased });
  }
  return out;
}

/**
 * Returns latest / first ratio for each of the 5 per-share series, or
 * null when history is empty or first value is zero.
 */
export function extractGrowthMultipliers(section: Section): GrowthMultipliers {
  function multiplier(description: string): number | null {
    const claim = findClaim(section.claims, description);
    if (!claim || claim.history.length === 0) return null;
    const first = claim.history[0].value;
    const last = claim.history[claim.history.length - 1].value;
    if (!isFiniteNumber(first) || first === 0 || !isFiniteNumber(last)) {
      return null;
    }
    return last / first;
  }

  return {
    rev: multiplier(DESC_REVENUE),
    gp: multiplier(DESC_GP),
    opi: multiplier(DESC_OPI),
    fcf: multiplier(DESC_FCF),
    ocf: multiplier(DESC_OCF),
  };
}
