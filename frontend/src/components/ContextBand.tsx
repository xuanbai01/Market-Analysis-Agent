/**
 * ContextBand — Phase 4.4.A.
 *
 * Thin 2-col grid wrapper holding ``BusinessCard`` (left, 40%) +
 * ``NewsList`` (right, 60%) between the HeroCard and the row-2
 * grid. Stacks 1-col below ``lg:``. Returns null when both children
 * sections are absent so the page doesn't render an empty band.
 */
import type { Section } from "../lib/schemas";
import { BusinessCard } from "./BusinessCard";
import { NewsList } from "./NewsList";

interface Props {
  ticker: string;
  businessSection?: Section;
  newsSection?: Section;
}

export function ContextBand({
  ticker,
  businessSection,
  newsSection,
}: Props) {
  if (!businessSection && !newsSection) return null;

  return (
    <div
      data-testid="context-band"
      className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-5"
    >
      {businessSection && (
        <div className="lg:col-span-2">
          <BusinessCard ticker={ticker} section={businessSection} />
        </div>
      )}
      {newsSection && (
        <div className={businessSection ? "lg:col-span-3" : "lg:col-span-5"}>
          <NewsList section={newsSection} />
        </div>
      )}
    </div>
  );
}
