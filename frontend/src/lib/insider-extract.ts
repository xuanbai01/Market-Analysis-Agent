/**
 * insider-extract — officer and director trades from the Insider Activity
 * section (2026-11).
 *
 * Mirrors app/services/form_4.py::DESCRIPTIONS and the person claims it
 * emits ("NAME (Role): net bought (+) or sold (−), last 6 months"), plus
 * research_derived.insider_claims. Matched by description, as the other
 * extractors do.
 */
import type { Claim, Section } from "./schemas";

const W = "last 6 months";
const D = {
  filings: `Form 4 filings about the company, ${W}`,
  first: "Earliest Form 4 filing in the window",
  last: "Most recent Form 4 filing",
  bought: `Purchases by officers and directors, ${W}`,
  buyers: `Officers and directors who bought, ${W}`,
  sold: `Sales by officers and directors, ${W}`,
  sellers: `Officers and directors who sold, ${W}`,
  plan: "Share of officer and director sales made under 10b5-1 trading plans",
  routine: `Grants, option exercises, tax withholdings and gifts, ${W} (not buys or sales)`,
  holderBought: `Purchases by 10% holders and other reporting owners, ${W}`,
  holderSold: `Sales by 10% holders and other reporting owners, ${W}`,
  soldShare: `Officer and director sales as a share of market cap, ${W}`,
  boughtShare: `Officer and director purchases as a share of market cap, ${W}`,
} as const;
const PERSON_SUFFIX = `): net bought (+) or sold (−), ${W}`;

export interface InsiderPerson {
  name: string;
  role: string;
  /** Bought minus sold, in dollars. */
  net: number;
}

export interface Insiders {
  filingCount: number;
  firstFiling: string | null;
  lastFiling: string | null;
  bought: number | null;
  buyers: number | null;
  sold: number | null;
  sellers: number | null;
  planShare: number | null;
  routine: number | null;
  holderBought: number | null;
  holderSold: number | null;
  soldShareOfMarketCap: number | null;
  boughtShareOfMarketCap: number | null;
  people: InsiderPerson[];
  narrative: string | null;
}

function num(claims: Claim[], description: string): number | null {
  const v = claims.find((c) => c.description === description)?.value;
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function str(claims: Claim[], description: string): string | null {
  const v = claims.find((c) => c.description === description)?.value;
  return typeof v === "string" && v ? v : null;
}

/** "NAME (Role): net …" → name and role. The role may hold parentheses. */
function person(claim: Claim): InsiderPerson | null {
  if (!claim.description.endsWith(PERSON_SUFFIX) || typeof claim.value !== "number") return null;
  const head = claim.description.slice(0, -PERSON_SUFFIX.length);
  const open = head.indexOf(" (");
  if (open <= 0) return null;
  return { name: head.slice(0, open), role: head.slice(open + 2), net: claim.value };
}

/** The section's insider data; null when there is nothing to show (no
 *  Form 4s, or a report built before this section existed). */
export function extractInsiders(section: Section | undefined): Insiders | null {
  if (!section) return null;
  const c = section.claims;
  const filingCount = num(c, D.filings);
  if (filingCount === null) return null;
  return {
    filingCount,
    firstFiling: str(c, D.first),
    lastFiling: str(c, D.last),
    bought: num(c, D.bought),
    buyers: num(c, D.buyers),
    sold: num(c, D.sold),
    sellers: num(c, D.sellers),
    planShare: num(c, D.plan),
    routine: num(c, D.routine),
    holderBought: num(c, D.holderBought),
    holderSold: num(c, D.holderSold),
    soldShareOfMarketCap: num(c, D.soldShare),
    boughtShareOfMarketCap: num(c, D.boughtShare),
    people: c.map(person).filter((p): p is InsiderPerson => p !== null),
    narrative: section.card_narrative ?? null,
  };
}
