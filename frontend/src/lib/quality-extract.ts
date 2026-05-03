/**
 * quality-extract — pure helpers that pull QualityCard's data out of
 * the Quality Section. Phase 4.2.
 *
 * Three responsibilities, each a pure function with no React coupling:
 *
 *   1. ``extractQualityRings(section)`` — ROE / ROIC / FCF margin for
 *      the 3 MetricRings at the top of QualityCard.
 *   2. ``extractMarginSeries(section)`` — gross / operating / FCF
 *      margin history series for the MultiLine chart.
 *   3. ``extractPrimaryQualityClaims(section)`` /
 *      ``extractAllQualityClaims(section)`` — 6+expand split for the
 *      claims table.
 *
 * Same description-matching philosophy as the other extractors: backend
 * keys don't survive the Pydantic flatten, so we match on the stable
 * descriptions defined in ``app/services/fundamentals.py::_DESCRIPTIONS``.
 *
 * The 6-claim default-display set is the analyst-priority cut: the four
 * margins (gross / operating / FCF / net) plus ROE + ROIC. The remaining
 * 10 claims live behind "Show all 16" — they're per-share growth
 * series, balance-sheet trends, and the YoY gross-margin delta.
 */
import type { Claim, Section } from "./schemas";
import type { MultiLineSeries } from "../components/MultiLine";

// Description strings — copy-paste from
// app/services/fundamentals.py::_DESCRIPTIONS so a backend rename fails
// the test suite loudly.
const DESC_ROE = "Return on equity";
const DESC_ROIC = "Return on invested capital (TTM)";
const DESC_GROSS_MARGIN = "Gross margin";
const DESC_OPERATING_MARGIN = "Operating margin";
const DESC_FCF_MARGIN = "Free cash flow margin";
const DESC_NET_PROFIT_MARGIN = "Net profit margin";

// 6-claim default-display set, in display order. The first 6 Quality
// claims a user sees in the hybrid view.
const PRIMARY_DESCRIPTIONS: readonly string[] = [
  DESC_ROE,
  DESC_GROSS_MARGIN,
  DESC_OPERATING_MARGIN,
  DESC_FCF_MARGIN,
  DESC_ROIC,
  DESC_NET_PROFIT_MARGIN,
];

// Strata accent colors per margin series (locked to backend categories).
const COLOR_QUALITY = "#7ad0a6";
const COLOR_GROWTH = "#c2d97a";
const COLOR_CASHFLOW = "#e8c277";

export interface QualityRings {
  roe: number | null;
  roic: number | null;
  fcfMargin: number | null;
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

function findNumericValue(
  claims: readonly Claim[],
  description: string,
): number | null {
  const claim = findClaim(claims, description);
  if (!claim || !isFiniteNumber(claim.value)) return null;
  return claim.value;
}

/**
 * Pull the 3 ring values from the Quality section. Each field is null
 * when the corresponding claim is missing or non-numeric.
 */
export function extractQualityRings(section: Section): QualityRings {
  return {
    roe: findNumericValue(section.claims, DESC_ROE),
    roic: findNumericValue(section.claims, DESC_ROIC),
    fcfMargin: findNumericValue(section.claims, DESC_FCF_MARGIN),
  };
}

/**
 * Build 3 series (gross / operating / FCF margin) for MultiLine. Each
 * series is included only when the corresponding claim has at least
 * one history point. Empty result is a valid response when nothing has
 * history yet (e.g. pre-3.2 cached reports).
 */
export function extractMarginSeries(section: Section): MultiLineSeries[] {
  const out: MultiLineSeries[] = [];

  const gross = findClaim(section.claims, DESC_GROSS_MARGIN);
  if (gross && gross.history.length > 0) {
    out.push({
      label: "Gross margin",
      color: COLOR_QUALITY,
      history: gross.history,
    });
  }

  const operating = findClaim(section.claims, DESC_OPERATING_MARGIN);
  if (operating && operating.history.length > 0) {
    out.push({
      label: "Operating margin",
      color: COLOR_GROWTH,
      history: operating.history,
    });
  }

  const fcf = findClaim(section.claims, DESC_FCF_MARGIN);
  if (fcf && fcf.history.length > 0) {
    out.push({
      label: "FCF margin",
      color: COLOR_CASHFLOW,
      history: fcf.history,
    });
  }

  return out;
}

/**
 * Return the 6 default-display Quality claims, in stable display order,
 * skipping any that aren't in the section. Result is < 6 only when the
 * upstream tool failed to populate part of the Quality contract.
 */
export function extractPrimaryQualityClaims(
  section: Section,
): Claim[] {
  const out: Claim[] = [];
  for (const desc of PRIMARY_DESCRIPTIONS) {
    const claim = findClaim(section.claims, desc);
    if (claim) out.push(claim);
  }
  return out;
}

/**
 * Return every claim in the Quality section in its original order.
 * Wrapper preserves the symmetry with ``extractPrimaryQualityClaims``
 * and gives the call site a single import surface.
 */
export function extractAllQualityClaims(section: Section): Claim[] {
  return [...section.claims];
}
