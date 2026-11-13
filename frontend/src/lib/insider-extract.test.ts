/**
 * insider-extract — the Insider Activity section's claims (app/services/
 * form_4.py, research_derived.insider_claims) read by description.
 */
import { describe, expect, it } from "vitest";

import type { Claim, ClaimValue, Section } from "./schemas";
import { extractInsiders } from "./insider-extract";

function claim(description: string, value: ClaimValue, detail?: string): Claim {
  return {
    description,
    value,
    source: { tool: "sec.form_4", fetched_at: "2026-11-13T17:00:00+00:00", detail },
    history: [],
  };
}

const W = "last 6 months";

function section(claims: Claim[]): Section {
  return { title: "Insider Activity", summary: "", confidence: "high", claims, card_narrative: "Routine selling." };
}

const NVDA = section([
  claim(`Form 4 filings about the company, ${W}`, 38),
  claim("Earliest Form 4 filing in the window", "2026-05-29"),
  claim("Most recent Form 4 filing", "2026-11-06"),
  claim(`Purchases by officers and directors, ${W}`, 0),
  claim(`Officers and directors who bought, ${W}`, 0),
  claim(`Sales by officers and directors, ${W}`, 1_378_200_000),
  claim(`Officers and directors who sold, ${W}`, 5),
  claim(`Net officer and director buying (+) or selling (−), ${W}`, -1_378_200_000),
  claim("Share of officer and director sales made under 10b5-1 trading plans", 0.0153),
  claim(`Grants, option exercises, tax withholdings and gifts, ${W} (not buys or sales)`, 32),
  claim(`Purchases by 10% holders and other reporting owners, ${W}`, 0),
  claim(`Sales by 10% holders and other reporting owners, ${W}`, 0),
  claim(`STEVENS MARK A (Director): net bought (+) or sold (−), ${W}`, -1_353_730_172, "bought $0, sold $1,353,730,172 across 21 trades"),
  claim(`Kress Colette (EVP & Chief Financial Officer): net bought (+) or sold (−), ${W}`, -7_648_632, "bought $0, sold $7,648,632 across 3 trades"),
  claim(`Officer and director sales as a share of market cap, ${W}`, 0.000313),
]);

describe("extractInsiders", () => {
  it("reads the totals, the plan share and the window", () => {
    const x = extractInsiders(NVDA);
    expect(x).not.toBeNull();
    expect(x?.filingCount).toBe(38);
    expect([x?.firstFiling, x?.lastFiling]).toEqual(["2026-05-29", "2026-11-06"]);
    expect([x?.bought, x?.buyers, x?.sold, x?.sellers]).toEqual([0, 0, 1_378_200_000, 5]);
    expect(x?.planShare).toBe(0.0153);
    expect(x?.routine).toBe(32);
    expect(x?.soldShareOfMarketCap).toBe(0.000313);
    expect(x?.boughtShareOfMarketCap).toBeNull();
    expect(x?.narrative).toBe("Routine selling.");
  });

  it("reads each top trader's name, role and net, in order", () => {
    const people = extractInsiders(NVDA)?.people ?? [];
    expect(people).toEqual([
      { name: "STEVENS MARK A", role: "Director", net: -1_353_730_172 },
      { name: "Kress Colette", role: "EVP & Chief Financial Officer", net: -7_648_632 },
    ]);
  });

  it("keeps a role that itself has parentheses", () => {
    const x = extractInsiders(
      section([
        claim(`Form 4 filings about the company, ${W}`, 1),
        claim(`DOE JANE (President (Americas)): net bought (+) or sold (−), ${W}`, 10),
      ]),
    );
    expect(x?.people).toEqual([{ name: "DOE JANE", role: "President (Americas)", net: 10 }]);
  });

  it("is null when the tool had nothing (no Form 4s, or a report built before this section)", () => {
    expect(extractInsiders(undefined)).toBeNull();
    expect(extractInsiders(section([claim(`Form 4 filings about the company, ${W}`, null)]))).toBeNull();
  });

  it("keeps a company with no recent filings, so the card can say so", () => {
    const x = extractInsiders(
      section([
        claim(`Form 4 filings about the company, ${W}`, 0),
        claim("Most recent Form 4 filing", "2026-01-05"),
        claim(`Sales by officers and directors, ${W}`, null),
      ]),
    );
    expect(x?.filingCount).toBe(0);
    expect(x?.lastFiling).toBe("2026-01-05");
    expect(x?.sold).toBeNull();
  });
});
