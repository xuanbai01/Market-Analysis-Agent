/**
 * cash-capital-extract — pure helpers for CashAndCapitalCard.
 * Phase 4.3.A.
 *
 * The card is cross-section: CapEx + SBC live in the Capital Allocation
 * section; Cash + Debt live in the Quality section. We expose three
 * helpers so the card itself stays compositional.
 *
 *   - extractCapexSbcSeries(capAlloc) → MultiLineSeries[] (CapEx + SBC)
 *   - extractCashDebtSeries(quality)  → MultiLineSeries[] (Cash + Debt)
 *   - extractNetCashPerShare(quality) → number | null  (cash − debt latest)
 *
 * Description matches mirror app/services/fundamentals.py::_DESCRIPTIONS.
 */
import type { Claim, Section } from "./schemas";
import type { MultiLineSeries } from "../components/MultiLine";

const DESC_CAPEX = "Capital expenditure per share";
const DESC_SBC = "Stock-based compensation per share";
const DESC_CASH = "Cash + short-term investments per share";
const DESC_DEBT = "Total debt per share";

const COLOR_CASH_ACCENT = "#e8c277";
const COLOR_EARN_ACCENT = "#d68dc6";
const COLOR_POS = "#5fbf8a";
const COLOR_NEG = "#e57c6e";

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function findClaim(
  claims: readonly Claim[],
  description: string,
): Claim | undefined {
  return claims.find((c) => c.description === description);
}

function seriesFor(
  section: Section | undefined,
  description: string,
  label: string,
  color: string,
): MultiLineSeries | null {
  if (!section) return null;
  const claim = findClaim(section.claims, description);
  if (!claim || claim.history.length === 0) return null;
  return { label, color, history: claim.history };
}

/**
 * CapEx + SBC per-share series for the top stack of CashAndCapitalCard.
 * Series with empty history are dropped.
 */
export function extractCapexSbcSeries(
  capAlloc: Section | undefined,
): MultiLineSeries[] {
  const out: MultiLineSeries[] = [];
  const capex = seriesFor(capAlloc, DESC_CAPEX, "CapEx", COLOR_CASH_ACCENT);
  if (capex) out.push(capex);
  const sbc = seriesFor(capAlloc, DESC_SBC, "SBC", COLOR_EARN_ACCENT);
  if (sbc) out.push(sbc);
  return out;
}

/**
 * Cash + Debt per-share series for the bottom stack of CashAndCapitalCard.
 * Series with empty history are dropped.
 */
export function extractCashDebtSeries(
  quality: Section | undefined,
): MultiLineSeries[] {
  const out: MultiLineSeries[] = [];
  const cash = seriesFor(quality, DESC_CASH, "Cash", COLOR_POS);
  if (cash) out.push(cash);
  const debt = seriesFor(quality, DESC_DEBT, "Debt", COLOR_NEG);
  if (debt) out.push(debt);
  return out;
}

/**
 * Net cash / share = cash − debt at latest quarter. Reads point-in-time
 * snapshot values rather than history[-1] so the headline matches what
 * the rest of the report cites for the same snapshot. Null when either
 * value is missing or non-numeric. Negative when debt > cash (debt-heavy
 * balance sheet).
 */
export function extractNetCashPerShare(
  quality: Section | undefined,
): number | null {
  if (!quality) return null;
  const cashClaim = findClaim(quality.claims, DESC_CASH);
  const debtClaim = findClaim(quality.claims, DESC_DEBT);
  if (!cashClaim || !debtClaim) return null;
  if (!isFiniteNumber(cashClaim.value) || !isFiniteNumber(debtClaim.value)) {
    return null;
  }
  return cashClaim.value - debtClaim.value;
}
