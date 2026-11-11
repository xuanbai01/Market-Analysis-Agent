/**
 * growth-extract — pulls 5 per-share growth series from the Quality
 * section, rebases each to its first history point = 100 so the
 * resulting MultiLine shows true relative growth on a shared axis.
 *
 * Phase 4.3.A.
 *
 * Helpers:
 *
 *   - extractPerSharePanels(section)    → { income, cashFlow } actual
 *                                         $/share series (the dashboard card)
 *   - extractGrowthSeries(section)      → MultiLineSeries[] (rebased; the
 *                                         two-ticker Compare overlay)
 *   - extractGrowthChanges(section)     → { rev, gp, opi, fcf, ocf }
 *                                         latest quarter vs the same
 *                                         quarter a year earlier.
 *   - extractAnnualPanels(section)      → { topLine, earnings } — up to
 *                                         eleven years from SEC filings
 *   - extractLongTermGrowth(section)    → { rev, opi, eps, fcf } multiple
 *                                         + compound annual rate over the span
 *
 * Description matches mirror app/services/fundamentals.py::_DESCRIPTIONS.
 * Tests pin them so a backend rename fails the suite loudly.
 */
import { shortPeriod } from "./chart-format";
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

export type GrowthKey = "rev" | "gp" | "opi" | "fcf" | "ocf";

/** One series' change: a percent when the base is positive, otherwise
 *  the dollar move (a percent of a loss misleads), with what it spans. */
export interface GrowthChange {
  kind: "pct" | "usd";
  value: number;
  /** "Q3 '26 vs Q3 '25" for a year-over-year change, else "since Q1 '26". */
  basis: string;
  yearOverYear: boolean;
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

export interface PerSharePanels {
  /** Revenue, Gross profit, Op income — the income-statement lines. */
  income: MultiLineSeries[];
  /** OCF, FCF — the cash-flow lines. */
  cashFlow: MultiLineSeries[];
}

const SHORT_LABELS: Record<string, string> = {
  [DESC_REVENUE]: "Rev",
  [DESC_GP]: "GP",
  [DESC_OPI]: "OpI",
  [DESC_OCF]: "OCF",
  [DESC_FCF]: "FCF",
};
const INCOME_ORDER = [DESC_REVENUE, DESC_GP, DESC_OPI];
const CASH_FLOW_ORDER = [DESC_OCF, DESC_FCF];

/**
 * 2026-11 (tasks/dogfood-2026-11.md #8): the per-share card plots the
 * actual $/share values. All five series share that unit, so they fit
 * one real axis without rebasing — which inflated small bases (NVDA FCF
 * $0.55 → "3.6×") and flipped the direction of negative ones. Split into
 * income vs cash-flow panels so five lines don't share one plot.
 * Series with fewer than 2 points are dropped.
 */
export function extractPerSharePanels(section: Section): PerSharePanels {
  const pick = (order: string[]): MultiLineSeries[] =>
    order.flatMap((description) => {
      const spec = SERIES_SPEC.find((s) => s.description === description);
      const claim = findClaim(section.claims, description);
      if (!spec || !claim) return [];
      const history = claim.history.filter((p) => isFiniteNumber(p.value));
      if (history.length < 2) return [];
      return [{ label: spec.label, shortLabel: SHORT_LABELS[description], color: spec.color, history }];
    });
  return { income: pick(INCOME_ORDER), cashFlow: pick(CASH_FLOW_ORDER) };
}

/** Beyond this (as a fraction, i.e. ±300%), a change shows as dollars. */
const MAX_PERCENT_CHANGE = 3;

/** "2026-Q3" → "2025-Q3"; null for other period shapes. */
function yearEarlier(period: string): string | null {
  const m = /^(\d{4})-Q([1-4])$/.exec(period);
  return m ? `${Number(m[1]) - 1}-Q${m[2]}` : null;
}

/**
 * Each per-share series' change from the same quarter a year earlier
 * (2026-11 chart audit). With ~5 quarters of history the old pills —
 * total multiplier ("1.1×") and per-quarter compound rate ("+1.8% / Q")
 * — said little, and the multiplier hid seasonality; five quarters
 * cover exactly one year-over-year comparison. Falls back to the change
 * since the first point when no year-earlier quarter exists. Null for a
 * series with fewer than 2 points.
 */
export function extractGrowthChanges(section: Section): Record<GrowthKey, GrowthChange | null> {
  function change(description: string): GrowthChange | null {
    const claim = findClaim(section.claims, description);
    if (!claim) return null;
    const h = [...claim.history]
      .filter((p) => isFiniteNumber(p.value))
      .sort((a, b) => (a.period < b.period ? -1 : 1));
    if (h.length < 2) return null;
    const last = h[h.length - 1];
    const target = yearEarlier(last.period);
    const yearAgo = target ? h.find((p) => p.period === target) : undefined;
    const base = yearAgo ?? h[0];
    const basis = yearAgo
      ? `${shortPeriod(last.period)} vs ${shortPeriod(base.period)}`
      : `since ${shortPeriod(base.period)}`;
    // A percent of a near-zero base reads as noise (RIVN's operating cash
    // flow per share: "-2560%"), so past ±300% the dollar move is shown.
    const pct = base.value > 0 ? last.value / base.value - 1 : null;
    if (pct !== null && Math.abs(pct) <= MAX_PERCENT_CHANGE) {
      return { kind: "pct", value: pct, basis, yearOverYear: !!yearAgo };
    }
    return { kind: "usd", value: last.value - base.value, basis, yearOverYear: !!yearAgo };
  }

  return {
    rev: change(DESC_REVENUE),
    gp: change(DESC_GP),
    opi: change(DESC_OPI),
    fcf: change(DESC_FCF),
    ocf: change(DESC_OCF),
  };
}

// ── 2026-11 — ten years of annual per-share history (SEC filings) ──────
// Mirrors app/services/annual_history.py::DESCRIPTIONS.

export const DESC_REVENUE_ANNUAL = "Revenue per share, annual (SEC filings)";
export const DESC_OPI_ANNUAL = "Operating income per share, annual (SEC filings)";
export const DESC_FCF_ANNUAL = "Free cash flow per share, annual (SEC filings)";
export const DESC_EPS_ANNUAL = "Diluted EPS, annual (SEC filings)";

export type AnnualKey = "rev" | "opi" | "eps" | "fcf";

interface AnnualSpec {
  key: AnnualKey;
  description: string;
  label: string;
  shortLabel: string;
  color: string;
}

// Revenue, operating income and FCF keep their quarterly-view colours;
// EPS (annual only) takes the slot gross profit has in the quarterly view.
export const ANNUAL_SPEC: AnnualSpec[] = [
  { key: "rev", description: DESC_REVENUE_ANNUAL, label: "Revenue", shortLabel: "Rev", color: COLOR_VAL },
  { key: "opi", description: DESC_OPI_ANNUAL, label: "Op income", shortLabel: "OpI", color: COLOR_CASH },
  { key: "eps", description: DESC_EPS_ANNUAL, label: "Diluted EPS", shortLabel: "EPS", color: COLOR_QUAL },
  { key: "fcf", description: DESC_FCF_ANNUAL, label: "FCF", shortLabel: "FCF", color: COLOR_EARN },
];

export interface AnnualPanels {
  /** Revenue and operating income per share. */
  topLine: MultiLineSeries[];
  /** Diluted EPS and free cash flow per share. */
  earnings: MultiLineSeries[];
}

function annualHistory(section: Section, description: string): ClaimHistoryPoint[] {
  const claim = findClaim(section.claims, description);
  if (!claim) return [];
  return claim.history
    .filter((p) => isFiniteNumber(p.value) && /^\d{4}$/.test(p.period))
    .sort((a, b) => (a.period < b.period ? -1 : 1));
}

/**
 * The annual series as two panels. Each panel gets its own scale: EPS
 * and FCF per share sit at a fraction of revenue per share and would
 * flatten on a shared one; every panel labels its axis. Series with
 * fewer than 2 years are dropped (banks have no FCF, many companies no
 * operating income line).
 */
export function extractAnnualPanels(section: Section): AnnualPanels {
  const pick = (keys: AnnualKey[]): MultiLineSeries[] =>
    keys.flatMap((key) => {
      const spec = ANNUAL_SPEC.find((s) => s.key === key)!;
      const history = annualHistory(section, spec.description);
      if (history.length < 2) return [];
      return [{ label: spec.label, shortLabel: spec.shortLabel, color: spec.color, history }];
    });
  return { topLine: pick(["rev", "opi"]), earnings: pick(["eps", "fcf"]) };
}

/** One annual series from its first year to its latest. */
export interface LongTermGrowth {
  firstPeriod: string;
  lastPeriod: string;
  firstValue: number;
  lastValue: number;
  years: number;
  /** last ÷ first — null unless both ends are positive. */
  multiple: number | null;
  /** Compound annual growth rate as a fraction — null unless both ends are positive. */
  cagr: number | null;
  /** last − first, in $/share (shown when a ratio would mislead). */
  change: number;
}

/**
 * Each annual series' growth over its whole span. A ratio of a loss (or
 * of a zero) misleads, so with a non-positive end only the dollar move
 * is given. Null for a series with fewer than 2 years.
 */
export function extractLongTermGrowth(section: Section): Record<AnnualKey, LongTermGrowth | null> {
  const growth = (description: string): LongTermGrowth | null => {
    const h = annualHistory(section, description);
    if (h.length < 2) return null;
    const first = h[0];
    const last = h[h.length - 1];
    const years = Number(last.period) - Number(first.period);
    const positive = first.value > 0 && last.value > 0 && years > 0;
    const multiple = positive ? last.value / first.value : null;
    return {
      firstPeriod: first.period,
      lastPeriod: last.period,
      firstValue: first.value,
      lastValue: last.value,
      years,
      multiple,
      cagr: multiple !== null ? multiple ** (1 / years) - 1 : null,
      change: last.value - first.value,
    };
  };
  return {
    rev: growth(DESC_REVENUE_ANNUAL),
    opi: growth(DESC_OPI_ANNUAL),
    eps: growth(DESC_EPS_ANNUAL),
    fcf: growth(DESC_FCF_ANNUAL),
  };
}
