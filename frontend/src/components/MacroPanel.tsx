/**
 * MacroPanel — Phase 4.3.A.
 *
 * Renders the row-4 rightmost card from `direction-strata.jsx`: a
 * vertical stack of mini area-chart panels (one per FRED series in
 * the resolved sector). Each panel: kicker label + current value
 * badge + 36-month area-chart sparkline.
 *
 * Reuses the existing LineChart primitive with `areaFill={true}` so
 * we don't grow the bundle for a one-off mini-chart variant.
 */
import { LineChart } from "./LineChart";
import { extractMacroPanels } from "../lib/macro-extract";
import type { ClaimHistoryPoint, Section } from "../lib/schemas";
import { NarrativeStrip } from "./NarrativeStrip";

interface Props {
  section: Section;
}

const COLOR_VAL = "#6cb6ff";
const COLOR_CASH = "#e8c277";
const COLOR_QUAL = "#7ad0a6";
const COLOR_GROWTH = "#c2d97a";
const COLOR_MACRO = "#7e9ad4";

// Cycle accent colors across panels in a stable order so successive
// FRED series get distinct chart strokes without exhausting the
// palette on a sector with 3 macro series.
const PANEL_COLORS = [COLOR_CASH, COLOR_VAL, COLOR_QUAL, COLOR_GROWTH, COLOR_MACRO];

function historyToLineChartData(history: ClaimHistoryPoint[]) {
  return history.map((p) => ({ ts: p.period, close: p.value }));
}

function formatLatest(n: number): string {
  // Macro values are mostly small percentages or indices in a few
  // hundred-million range. Keep two-decimals for percent-shaped values
  // and two-decimals for everything else; the units are conveyed in
  // the kicker / observation date row anyway.
  if (Math.abs(n) >= 100) return n.toFixed(0);
  return n.toFixed(2);
}

export function MacroPanel({ section }: Props) {
  const panels = extractMacroPanels(section);

  // Phase 4.5.C — return null when no series have data so
  // ``SymbolDetailPage``'s row 4 can collapse cleanly. Used to render
  // a "Macro context unavailable" placeholder card; that wasted a
  // column slot on cached reports without FRED data.
  if (panels.length === 0) {
    return null;
  }

  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-macro">
        Macro · FRED
      </div>

      <div className="flex flex-col gap-3">
        {panels.map((panel, i) => {
          const color = PANEL_COLORS[i % PANEL_COLORS.length];
          return (
            <div
              key={panel.label}
              className="rounded-md bg-strata-raise px-3 py-3"
            >
              <div className="mb-1 flex items-baseline justify-between">
                <span
                  className="font-mono text-[10px] uppercase tracking-kicker"
                  style={{ color }}
                >
                  {panel.label}
                </span>
                <span className="font-mono tabular text-base font-medium text-strata-hi">
                  {formatLatest(panel.latest)}
                </span>
              </div>
              <LineChart
                data={historyToLineChartData(panel.history)}
                width={280}
                height={50}
                strokeColor={color}
                fillColor={color}
                areaFill
                ariaLabel={`${panel.label} area chart`}
              />
            </div>
          );
        })}
      </div>

      {section.summary && (
        <p className="mt-3 rounded-md bg-strata-raise px-3 py-2 text-xs leading-relaxed text-strata-dim">
          {section.summary}
        </p>
      )}

      <NarrativeStrip text={section.card_narrative} />
    </section>
  );
}
