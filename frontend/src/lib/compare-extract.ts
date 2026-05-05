/**
 * compare-extract — pure helpers that pull paired metric values out of
 * two ResearchReports for the Compare page (`/compare?a=X&b=Y`).
 *
 * Phase 4.6.A.
 *
 * Same description-matching philosophy as the per-card extractors —
 * backend Pydantic flattens claim keys, so the frontend matches on the
 * stable description strings copy-pasted from
 * ``app/services/fundamentals.py::_DESCRIPTIONS``.
 *
 * The Compare-page-specific concerns each extractor handles:
 *
 *   - Pairing: every cell carries ``valueA`` (left ticker) + ``valueB``
 *     (right ticker) instead of subject-vs-peer-median.
 *   - Direction: ``lowerIsBetter`` is set per metric so the renderer
 *     picks the right "winner" highlight without re-reading metric
 *     semantics.
 *   - Side accent: chart series colors A vs B come from this module so
 *     the entire compare page reads the two tickers in consistent hues.
 */
import type { Claim, ClaimHistoryPoint, ResearchReport, Section } from "./schemas";
import type { MultiLineSeries } from "../components/MultiLine";

// Strata accents — A side leans valuation cyan, B side leans earnings violet.
// Hand-picked to match the mockup at docs/screenshots/image-1777831012413.png.
export const COMPARE_COLOR_A = "#6cb6ff";
export const COMPARE_COLOR_B = "#d68dc6";

// Description strings — single source of truth.
const DESC_FORWARD_PE = "P/E ratio (forward, analyst consensus)";
const DESC_PS = "Price-to-sales ratio (trailing 12 months)";
const DESC_EV_EBITDA = "Enterprise value to EBITDA";
const DESC_GROSS_MARGIN = "Gross margin";
const DESC_OPERATING_MARGIN = "Operating margin";
const DESC_FCF_MARGIN = "Free cash flow margin";
const DESC_ROIC = "Return on invested capital (TTM)";
const DESC_REVENUE_PER_SHARE = "Revenue per share";
const DESC_FCF_PER_SHARE = "Free cash flow per share";
const DESC_MARKET_CAP = "Market capitalization";

// ── Types ────────────────────────────────────────────────────────────

export interface CompareHeroData {
  symbol: string;
  name: string | null;
  sector: string | null;
  marketCap: number | null;
}

export type CompareMetricKey =
  | "forward_pe"
  | "p_s"
  | "ev_ebitda"
  | "gross_margin"
  | "operating_margin"
  | "fcf_margin"
  | "roic";

export interface CompareMetricCell {
  key: CompareMetricKey;
  /** Display label (kicker eyebrow). */
  label: string;
  /** Description string used for the underlying lookup. */
  description: string;
  valueA: number | null;
  valueB: number | null;
  /** Direction hint — true when smaller is better (valuation). */
  lowerIsBetter: boolean;
}

// ── Internal helpers ────────────────────────────────────────────────

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function findSection(report: ResearchReport, title: string): Section | undefined {
  return report.sections.find((s) => s.title === title);
}

function findClaim(claims: readonly Claim[], description: string): Claim | undefined {
  return claims.find((c) => c.description === description);
}

function numericValue(claims: readonly Claim[] | undefined, description: string): number | null {
  if (!claims) return null;
  const claim = findClaim(claims, description);
  if (!claim || !isFiniteNumber(claim.value)) return null;
  return claim.value;
}

function rebaseHistory(history: readonly ClaimHistoryPoint[]): ClaimHistoryPoint[] | null {
  if (history.length === 0) return null;
  const base = history[0].value;
  if (!isFiniteNumber(base) || base === 0) return null;
  return history.map((p) => ({ period: p.period, value: (p.value / base) * 100 }));
}

// ── Hero ────────────────────────────────────────────────────────────

export function extractCompareHeroData(report: ResearchReport): CompareHeroData {
  // Market cap may live in either Capital Allocation or Valuation depending
  // on the focus + builder; scan all sections rather than guessing.
  let marketCap: number | null = null;
  for (const section of report.sections) {
    const value = numericValue(section.claims, DESC_MARKET_CAP);
    if (value !== null) {
      marketCap = value;
      break;
    }
  }
  return {
    symbol: report.symbol,
    name: report.name ?? null,
    sector: report.sector ?? null,
    marketCap,
  };
}

// ── Metric rows ─────────────────────────────────────────────────────

const VALUATION_SPECS: { key: CompareMetricKey; label: string; description: string }[] = [
  { key: "forward_pe", label: "P/E FWD", description: DESC_FORWARD_PE },
  { key: "p_s", label: "P/S", description: DESC_PS },
  { key: "ev_ebitda", label: "EV/EBITDA", description: DESC_EV_EBITDA },
];

const QUALITY_SPECS: { key: CompareMetricKey; label: string; description: string }[] = [
  { key: "gross_margin", label: "GROSS MARGIN", description: DESC_GROSS_MARGIN },
  { key: "operating_margin", label: "OPERATING MARGIN", description: DESC_OPERATING_MARGIN },
  { key: "fcf_margin", label: "FCF MARGIN", description: DESC_FCF_MARGIN },
  { key: "roic", label: "ROIC", description: DESC_ROIC },
];

function buildCells(
  a: ResearchReport,
  b: ResearchReport,
  sectionTitle: string,
  specs: typeof VALUATION_SPECS,
  lowerIsBetter: boolean,
): CompareMetricCell[] {
  const aSection = findSection(a, sectionTitle);
  const bSection = findSection(b, sectionTitle);
  return specs.map(({ key, label, description }) => ({
    key,
    label,
    description,
    valueA: numericValue(aSection?.claims, description),
    valueB: numericValue(bSection?.claims, description),
    lowerIsBetter,
  }));
}

export function extractCompareValuationMetrics(
  a: ResearchReport,
  b: ResearchReport,
): CompareMetricCell[] {
  return buildCells(a, b, "Valuation", VALUATION_SPECS, true);
}

export function extractCompareQualityMetrics(
  a: ResearchReport,
  b: ResearchReport,
): CompareMetricCell[] {
  return buildCells(a, b, "Quality", QUALITY_SPECS, false);
}

// ── Margin overlay (operating margin, both tickers, shared axis) ────

function operatingMarginSeries(report: ResearchReport, color: string): MultiLineSeries | null {
  const quality = findSection(report, "Quality");
  const claim = quality ? findClaim(quality.claims, DESC_OPERATING_MARGIN) : undefined;
  if (!claim || claim.history.length === 0) return null;
  return { label: report.symbol, color, history: [...claim.history] };
}

export function extractCompareMarginOverlay(
  a: ResearchReport,
  b: ResearchReport,
): MultiLineSeries[] {
  const out: MultiLineSeries[] = [];
  const aSeries = operatingMarginSeries(a, COMPARE_COLOR_A);
  if (aSeries) out.push(aSeries);
  const bSeries = operatingMarginSeries(b, COMPARE_COLOR_B);
  if (bSeries) out.push(bSeries);
  return out;
}

// ── Growth overlay (Rev + FCF per share, rebased, both tickers) ────

interface GrowthSpec {
  description: string;
  metric: "Rev" | "FCF";
}

const GROWTH_SPECS: GrowthSpec[] = [
  { description: DESC_REVENUE_PER_SHARE, metric: "Rev" },
  { description: DESC_FCF_PER_SHARE, metric: "FCF" },
];

function rebasedSeriesFor(
  report: ResearchReport,
  spec: GrowthSpec,
  color: string,
): MultiLineSeries | null {
  const quality = findSection(report, "Quality");
  const claim = quality ? findClaim(quality.claims, spec.description) : undefined;
  if (!claim) return null;
  const rebased = rebaseHistory(claim.history);
  if (!rebased) return null;
  return { label: `${report.symbol} ${spec.metric}`, color, history: rebased };
}

export function extractCompareGrowthOverlay(
  a: ResearchReport,
  b: ResearchReport,
): MultiLineSeries[] {
  const out: MultiLineSeries[] = [];
  for (const spec of GROWTH_SPECS) {
    const aSeries = rebasedSeriesFor(a, spec, COMPARE_COLOR_A);
    if (aSeries) out.push(aSeries);
    const bSeries = rebasedSeriesFor(b, spec, COMPARE_COLOR_B);
    if (bSeries) out.push(bSeries);
  }
  return out;
}
