/**
 * Helpers for the analyst view (Phase 5): resolve a point's claim_refs
 * against the report, and scroll to the card that shows a section.
 */
import type { Claim, ClaimRef, ResearchReport } from "./schemas";

/** Sections drawn inside another section's card. */
const ANCHOR_ALIASES: Record<string, string> = {
  // The peer scatter lives in the Valuation card.
  Peers: "Valuation",
};

export function anchorFor(section: string): string {
  return ANCHOR_ALIASES[section] ?? section;
}

export interface ResolvedRef {
  section: string;
  claim: Claim;
}

/** The claim a ref points at, or null if the report doesn't have it. */
export function resolveRef(report: ResearchReport, ref: ClaimRef): ResolvedRef | null {
  const section = report.sections.find((s) => s.title === ref.section);
  const claim = section?.claims[ref.index];
  return section && claim ? { section: section.title, claim } : null;
}

/** Scroll the card carrying ``data-section-anchor`` for this section into view. */
export function scrollToSection(section: string): boolean {
  const target = document.querySelector<HTMLElement>(
    `[data-section-anchor="${anchorFor(section)}"]`,
  );
  if (!target) return false;
  target.scrollIntoView({ behavior: "smooth", block: "start" });
  return true;
}
