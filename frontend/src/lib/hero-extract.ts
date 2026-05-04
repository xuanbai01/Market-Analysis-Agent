/**
 * hero-extract — pure helper that pulls the data the HeroCard needs
 * out of a ResearchReport. Phase 4.1.
 *
 * Same description-matching philosophy as Phase 3.3.B's
 * `featured-claim.ts` and 3.3.C's `peer-grouping.ts` — the schema
 * flattens claim keys into per-section lists, so the backend keys
 * don't survive the round-trip; we match on the stable
 * `_DESCRIPTIONS` strings instead.
 *
 * `name` and `sector` are top-level on ResearchReport (Phase 4.1
 * orchestrator change) so they don't need claim-traversal.
 */
import type { Claim, ResearchReport, Section } from "./schemas";

export interface HeroData {
  name: string | null;
  sector: string | null;
  // Hero meta line
  marketCap: number | null;
  fiftyTwoWeekHigh: number | null;
  fiftyTwoWeekLow: number | null;
  // 3 featured stats (healthy default trio)
  forwardPE: { value: number; peerMedian: number | null } | null;
  roicTTM: number | null;
  fcfMargin: number | null;
  // Phase 4.5.A — distressed-mode replacement value. Read by HeroCard
  // in the swap path when ``layout_signals.is_unprofitable_ttm``.
  priceToSales: { value: number; peerMedian: number | null } | null;
}

const DESC_FORWARD_PE = "P/E ratio (forward, analyst consensus)";
const DESC_ROIC_TTM = "Return on invested capital (TTM)";
const DESC_FCF_MARGIN = "Free cash flow margin";
const DESC_MARKET_CAP = "Market capitalization";
const DESC_52W_HIGH = "52-week high";
const DESC_52W_LOW = "52-week low";
const DESC_PEER_MEDIAN_FORWARD_PE = "Peer median: P/E ratio (forward, analyst consensus)";
const DESC_PRICE_TO_SALES = "Price-to-sales ratio (trailing 12 months)";
const DESC_PEER_MEDIAN_PRICE_TO_SALES = "Peer median: Price-to-sales ratio (trailing 12 months)";

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function findClaimByDescription(
  sections: readonly Section[],
  description: string,
): Claim | undefined {
  for (const section of sections) {
    for (const claim of section.claims) {
      if (claim.description === description) return claim;
    }
  }
  return undefined;
}

function findNumericValue(
  sections: readonly Section[],
  description: string,
): number | null {
  const claim = findClaimByDescription(sections, description);
  if (!claim) return null;
  return isFiniteNumber(claim.value) ? claim.value : null;
}

export function extractHeroData(report: ResearchReport): HeroData | null {
  const fwdPE = findNumericValue(report.sections, DESC_FORWARD_PE);
  const peerFwdPE = findNumericValue(
    report.sections,
    DESC_PEER_MEDIAN_FORWARD_PE,
  );
  const ps = findNumericValue(report.sections, DESC_PRICE_TO_SALES);
  const peerPS = findNumericValue(
    report.sections,
    DESC_PEER_MEDIAN_PRICE_TO_SALES,
  );

  return {
    name: report.name ?? null,
    sector: report.sector ?? null,
    marketCap: findNumericValue(report.sections, DESC_MARKET_CAP),
    fiftyTwoWeekHigh: findNumericValue(report.sections, DESC_52W_HIGH),
    fiftyTwoWeekLow: findNumericValue(report.sections, DESC_52W_LOW),
    forwardPE: fwdPE !== null ? { value: fwdPE, peerMedian: peerFwdPE } : null,
    roicTTM: findNumericValue(report.sections, DESC_ROIC_TTM),
    fcfMargin: findNumericValue(report.sections, DESC_FCF_MARGIN),
    priceToSales: ps !== null ? { value: ps, peerMedian: peerPS } : null,
  };
}
