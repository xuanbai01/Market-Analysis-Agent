/**
 * valuation-history-extract — a company's multiples at each fiscal
 * year-end, and today's reading against them (2026-11).
 *
 * "Is this expensive against its own history" was the gap ADR 0004 named
 * first; the Valuation card could only compare with peers. The backend
 * prices each fiscal year (app/services/valuation_history.py) and derives
 * the median and today's premium or discount to it
 * (research_derived.valuation_history_claims). This reads those claims
 * out of the Valuation section by description, as the other extractors
 * do: keys don't survive the schema's flatten to a claim list.
 *
 * The descriptions below mirror the backend's; the derived ones carry
 * numbers ("…median of 14.00 across 5 fiscal year-ends…"), so they are
 * matched by their fixed prefix.
 */
import type { Claim, ClaimHistoryPoint, ResearchReport } from "./schemas";

export type OwnHistoryKey = "pe" | "ps" | "pfcf";

export interface OwnHistoryPanel {
  key: OwnHistoryKey;
  /** Panel title. */
  label: string;
  /** One point per fiscal year-end that has a multiple, oldest first. */
  history: ClaimHistoryPoint[];
  /** Median of those year-ends; null with fewer than the backend needs. */
  median: number | null;
  /** Today's trailing multiple; null on a loss or when it isn't reported. */
  today: number | null;
  /** Today over the median, minus one; null when either is missing. */
  premium: number | null;
}

interface Spec {
  key: OwnHistoryKey;
  label: string;
  history: string;
  today: string;
  medianPrefix: string;
  premiumPrefix: string;
}

const SPECS: Spec[] = [
  {
    key: "pe",
    label: "P/E",
    history: "P/E at fiscal year-end (SEC filings)",
    today: "P/E ratio (trailing 12 months)",
    medianPrefix: "Median P/E across ",
    premiumPrefix: "Trailing P/E vs its own median of ",
  },
  {
    key: "ps",
    label: "Price / sales",
    history: "Price-to-sales at fiscal year-end (SEC filings)",
    today: "Price-to-sales ratio (trailing 12 months)",
    medianPrefix: "Median price-to-sales across ",
    premiumPrefix: "Price-to-sales vs its own median of ",
  },
  {
    key: "pfcf",
    label: "Price / free cash flow",
    history: "Price-to-free-cash-flow at fiscal year-end (SEC filings)",
    today: "Price-to-free-cash-flow (trailing 12 months)",
    medianPrefix: "Median price-to-free-cash-flow across ",
    premiumPrefix: "Price-to-free-cash-flow vs its own median of ",
  },
];

/** A line needs two points. */
const MIN_POINTS = 2;

function numeric(claim: Claim | undefined): number | null {
  return claim && typeof claim.value === "number" && Number.isFinite(claim.value) ? claim.value : null;
}

/** The own-history panels a report can draw; [] for a report built
 *  before the year-end multiples or with too little history. */
export function extractOwnHistory(report: ResearchReport): OwnHistoryPanel[] {
  const claims = report.sections.find((s) => s.title === "Valuation")?.claims ?? [];
  const exact = (description: string) => claims.find((c) => c.description === description);
  const prefixed = (prefix: string) => claims.find((c) => c.description.startsWith(prefix));

  const panels: OwnHistoryPanel[] = [];
  for (const spec of SPECS) {
    const history = (exact(spec.history)?.history ?? []).filter((p) => Number.isFinite(p.value));
    if (history.length < MIN_POINTS) continue;
    panels.push({
      key: spec.key,
      label: spec.label,
      history,
      median: numeric(prefixed(spec.medianPrefix)),
      today: numeric(exact(spec.today)),
      premium: numeric(prefixed(spec.premiumPrefix)),
    });
  }
  return panels;
}
