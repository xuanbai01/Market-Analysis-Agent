/**
 * business-extract — pulls the Business section's claims into the
 * shape ``BusinessCard`` renders. Phase 4.4.A.
 *
 * Description matches mirror ``app/services/business_info.py::
 * _DESCRIPTIONS`` verbatim. Pin them in tests so a backend rename
 * fails the suite loudly.
 */
import type { Claim, Section } from "./schemas";

const DESC_SUMMARY = "Business description (from 10-K filing)";
const DESC_HQ = "Headquarters location";
const DESC_EMPLOYEES = "Full-time employee count";

export interface BusinessInfo {
  summary: string | null;
  hq: string | null;
  employeeCount: number | null;
}

function findClaim(
  claims: readonly Claim[],
  description: string,
): Claim | undefined {
  return claims.find((c) => c.description === description);
}

function asString(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v : null;
}

function asNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/**
 * Returns the three Business-card fields when present, ``null`` for
 * each missing/malformed field. Never throws.
 */
export function extractBusinessInfo(section: Section): BusinessInfo {
  const summaryClaim = findClaim(section.claims, DESC_SUMMARY);
  const hqClaim = findClaim(section.claims, DESC_HQ);
  const employeesClaim = findClaim(section.claims, DESC_EMPLOYEES);

  return {
    summary: summaryClaim ? asString(summaryClaim.value) : null,
    hq: hqClaim ? asString(hqClaim.value) : null,
    employeeCount: employeesClaim ? asNumber(employeesClaim.value) : null,
  };
}
