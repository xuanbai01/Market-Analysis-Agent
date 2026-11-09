/**
 * RiskDiffCard — Phase 4.3.A.
 *
 * Renders the row-4 middle card from `direction-strata.jsx`. Inline
 * horizontal bar chart of the 4 aggregate counts from the Risk
 * Factors section (added / removed / kept / char_delta), plus a
 * one-sentence prose summary that frames the year-over-year shift
 * as "expanded" / "shrank" / "stable".
 *
 * Pre-4.3.B these are aggregate paragraph counts. 4.3.B will add
 * per-category bucketing via Haiku classification — this card
 * upgrades to per-category bars when those fields land in the
 * payload (RiskDiffCard already gates on extractRiskDiffBars
 * returning null, so pre-4.3.B reports continue to render).
 */
import {
  extractRiskCategoryDeltas,
  extractRiskDiffBars,
  extractRiskDiffSummary,
  type RiskCategoryDelta,
  type RiskDiffBars,
  type RiskDiffFraming,
} from "../lib/risk-extract";
import type { Section } from "../lib/schemas";
import { NarrativeStrip } from "./NarrativeStrip";

interface Props {
  section: Section;
}

// Added risk text in the risk accent, dropped in green: the two poles of
// one diverging scale. Kept paragraphs are neutral context.
const ADDED_CLASS = "bg-strata-neg";
const DROPPED_CLASS = "bg-strata-pos";
const KEPT_CLASS = "bg-strata-muted";

/** A net change of ±1 must not fill a bar: scales never go below this. */
const MIN_CATEGORY_SCALE = 5;

const FRAME_TEXT: Record<RiskDiffFraming, string> = {
  expanded: "Disclosure expanded.",
  shrank: "Disclosure shrank.",
  reworked: "About the same length, reworked.",
  stable: "Disclosure stable.",
};

function formatNetDelta(n: number): string {
  if (n > 0) return `+${n} ¶`;
  if (n < 0) return `${n} ¶`;
  return "0 ¶";
}

function formatChars(n: number): string {
  const abs = Math.abs(n).toLocaleString("en-US");
  return `${n > 0 ? "+" : n < 0 ? "−" : ""}${abs}`;
}

export function RiskDiffCard({ section }: Props) {
  const bars = extractRiskDiffBars(section);
  const summary = extractRiskDiffSummary(section);
  // Phase 4.3.B — when the categorizer has stamped per-category deltas
  // onto the section, prefer that view over the aggregate bars.
  const categoryDeltas = extractRiskCategoryDeltas(section);

  // Phase 4.5.C — null when the diff isn't computable, so the dashboard
  // row collapses to the cards that have data.
  if (!bars || !summary) {
    return null;
  }

  return (
    <section className="flex h-full flex-col rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-risk">
        10-K risk factors · vs prior year
      </div>

      {categoryDeltas ? <CategoryBars deltas={categoryDeltas} /> : <AggregateBars bars={bars} />}

      <div className="mt-4 rounded-md bg-strata-raise px-3 py-2 text-xs leading-relaxed text-strata-dim">
        <span className="text-strata-fg">{FRAME_TEXT[summary.framing]}</span>{" "}
        {bars.added} added · {bars.removed} dropped · {bars.kept} kept (net{" "}
        <span
          className={
            summary.netDelta > 0
              ? "text-strata-risk"
              : summary.netDelta < 0
                ? "text-strata-pos"
                : "text-strata-fg"
          }
        >
          {formatNetDelta(summary.netDelta)}
        </span>
        ; {formatChars(bars.charDelta)} characters).
      </div>

      <NarrativeStrip text={section.card_narrative} />
    </section>
  );
}

/**
 * Net paragraphs per topic (added − dropped) on one diverging scale:
 * dropped to the left of the centre line, added to the right. The scale
 * never goes below ±5, so a ±1 change draws a short bar instead of a
 * full one (2026-11 chart audit: every KO bar filled its track, and the
 * labels rendered at about 7 px inside a shrunken SVG).
 */
function CategoryBars({ deltas }: { deltas: RiskCategoryDelta[] }) {
  const scale = Math.max(MIN_CATEGORY_SCALE, ...deltas.map((d) => Math.abs(d.delta)));
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
        <span>Net paragraphs by topic</span>
        <span className="normal-case tracking-normal">◀ dropped · added ▶</span>
      </div>
      <ul data-testid="risk-category-bars" className="space-y-1.5" aria-label="Net change in risk paragraphs by topic">
        {deltas.map((d) => {
          const pct = `${(Math.abs(d.delta) / scale) * 100}%`;
          return (
            <li
              key={d.category}
              data-row="risk-category-bar"
              className="grid grid-cols-[minmax(0,8.5rem)_1fr_1fr_2.25rem] items-center text-xs"
            >
              <span className="truncate pr-2 text-strata-fg" title={d.label}>
                {d.label}
              </span>
              <span className="flex h-2.5 justify-end">
                {d.delta < 0 && <span className={`h-full rounded-l ${DROPPED_CLASS}`} style={{ width: pct }} />}
              </span>
              <span className="flex h-2.5 border-l border-strata-muted">
                {d.delta > 0 && <span className={`h-full rounded-r ${ADDED_CLASS}`} style={{ width: pct }} />}
              </span>
              <span className="text-right font-mono tabular text-strata-hi">
                {d.delta > 0 ? `+${d.delta}` : `${d.delta}`}
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/**
 * Fallback without per-topic data: added, dropped and kept paragraphs on
 * one shared scale, so churn reads against the size of the section. The
 * character change used to be a fourth bar on its own scale; it now
 * sits in the summary line.
 */
function AggregateBars({ bars }: { bars: RiskDiffBars }) {
  const rows = [
    { label: "Added", value: bars.added, cls: ADDED_CLASS },
    { label: "Dropped", value: bars.removed, cls: DROPPED_CLASS },
    { label: "Kept", value: bars.kept, cls: KEPT_CLASS },
  ];
  const max = Math.max(1, ...rows.map((r) => r.value));
  return (
    <ul data-testid="risk-diff-bars" className="space-y-1.5" aria-label="Risk paragraphs added, dropped and kept">
      {rows.map((r) => (
        <li
          key={r.label}
          data-row="risk-diff-bar"
          className="grid grid-cols-[4.5rem_1fr_3rem] items-center text-xs"
        >
          <span className="text-strata-fg">{r.label}</span>
          <span className="flex h-2.5">
            <span className={`h-full rounded-r ${r.cls}`} style={{ width: `${Math.max(1, (r.value / max) * 100)}%` }} />
          </span>
          <span className="text-right font-mono tabular text-strata-hi">{r.value}</span>
        </li>
      ))}
    </ul>
  );
}
