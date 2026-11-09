/**
 * NarrativeStrip — Phase 4.4.B per-card narrative.
 *
 * Renders the LLM's 1-2 sentence headline+delta tagline at the bottom
 * of a dedicated dashboard card (Quality / Earnings / PerShareGrowth /
 * RiskDiff / Macro). Visual: faint inset card-within-card, raised
 * background, muted prose with the headline word in the high-contrast
 * foreground.
 *
 * Returns null when ``text`` is null / undefined / empty / whitespace
 * so older cached rows (pre-4.4.B) and sections where the model
 * declined to write one don't render an empty card-within-card.
 *
 * Usage in a card:
 *
 *   <section className="rounded-md border ...">
 *     ... data, charts, tiles ...
 *     <NarrativeStrip text={section.card_narrative} />
 *   </section>
 *
 * The strip carries no ticker / section context of its own — the
 * surrounding card supplies that. Keep it dumb.
 */
interface Props {
  text: string | null | undefined;
}

export function NarrativeStrip({ text }: Props) {
  if (text === null || text === undefined) return null;
  if (!text.trim()) return null;

  // ``mt-auto`` pins the strip to the bottom of a card stretched to its
  // row's height (cards are flex columns); ``pt-4`` keeps the gap.
  return (
    <div className="mt-auto pt-4">
      <p
        data-testid="card-narrative"
        className="rounded-md bg-strata-raise px-3 py-2 text-xs leading-relaxed text-strata-fg"
      >
        {text}
      </p>
    </div>
  );
}
