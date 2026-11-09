/**
 * capital-returns-extract — what the Capital Allocation section says
 * about returning and reinvesting cash, for CapitalReturnsCard.
 *
 * Descriptions match app/services/fundamentals.py and the ADR 0007
 * derived claims in app/services/research_derived.py exactly; a backend
 * rename shows up here as a missing stat, not a crash.
 */
import { formatClaimValue } from "./format";
import type { Claim, Section } from "./schemas";

export const DESC = {
  dividendYield: "Forward dividend yield",
  buybackYield: "Buyback yield (latest fiscal year)",
  shareholderYield: "Shareholder yield (forward dividend + latest-year buybacks)",
  payout: "Dividend payout ratio (forward dividend ÷ trailing earnings)",
  coverage: "Free cash flow ÷ dividends paid (coverage)",
  fcfYield: "Free cash flow yield (trailing 12 months)",
  capexOfRevenue: "Capex as % of revenue (trailing 12 months)",
  capexOfOcf: "Capex as % of operating cash flow (trailing 12 months)",
  sbcOfFcf: "Stock-based compensation as % of free cash flow (trailing 12 months)",
  marketCap: "Market capitalization",
  shortDays: "Short interest, days-to-cover",
} as const;

export interface CapitalStat {
  label: string;
  value: string;
  description: string;
}

export interface CapitalReturns {
  shareholderYield: string | null;
  dividendYield: string | null;
  buybackYield: string | null;
  stats: CapitalStat[];
  marketCap: string | null;
  shortDays: string | null;
}

function claimFor(section: Section, description: string): Claim | null {
  const claim = section.claims.find((c) => c.description === description);
  return claim && typeof claim.value === "number" && Number.isFinite(claim.value) ? claim : null;
}

function display(section: Section, description: string): string | null {
  const claim = claimFor(section, description);
  return claim ? formatClaimValue(claim.value, claim.unit) : null;
}

const STAT_SPECS: { label: string; description: string; format?: (v: number) => string }[] = [
  { label: "Payout ratio", description: DESC.payout },
  { label: "FCF covers dividend", description: DESC.coverage, format: (v) => `${v.toFixed(2)}×` },
  { label: "FCF yield", description: DESC.fcfYield },
  { label: "Capex ÷ revenue", description: DESC.capexOfRevenue },
  { label: "Capex ÷ op. cash flow", description: DESC.capexOfOcf },
  { label: "SBC ÷ free cash flow", description: DESC.sbcOfFcf },
];

export function extractCapitalReturns(section: Section): CapitalReturns {
  const stats = STAT_SPECS.flatMap((spec) => {
    const claim = claimFor(section, spec.description);
    if (!claim) return [];
    const value = spec.format ? spec.format(claim.value as number) : formatClaimValue(claim.value, claim.unit);
    return [{ label: spec.label, value, description: spec.description }];
  });
  const shortDays = claimFor(section, DESC.shortDays);
  return {
    shareholderYield: display(section, DESC.shareholderYield),
    dividendYield: display(section, DESC.dividendYield),
    buybackYield: display(section, DESC.buybackYield),
    stats,
    marketCap: display(section, DESC.marketCap),
    shortDays: shortDays ? `${(shortDays.value as number).toFixed(1)} days` : null,
  };
}

/** Whether the card has anything to show (the dashboard skips it if not). */
export function hasCapitalReturns(section: Section | undefined): boolean {
  if (!section) return false;
  const r = extractCapitalReturns(section);
  return Boolean(r.shareholderYield || r.dividendYield || r.buybackYield || r.stats.length);
}
