/**
 * MacroPanel — one small chart per FRED series for the ticker's sector.
 * Phase 4.3.A; redrawn in the 2026-11 chart audit.
 *
 * Each panel: the series name, its latest value in its own unit, the
 * change over the plotted window, and a line on a labelled axis (low /
 * high and first / last month). Until the audit these were area charts
 * whose fill started at the series' minimum rather than zero (an area
 * implies a zero baseline), with no dates or units, each panel in a
 * different colour that meant nothing, and labels set in that colour.
 *
 * Renders only with FRED data (``FRED_API_KEY`` on the backend);
 * returns null otherwise so the dashboard row collapses.
 */
import { extractMacroPanels, type MacroPanelSpec } from "../lib/macro-extract";
import type { ClaimHistoryPoint, Section } from "../lib/schemas";
import { LineChart } from "./LineChart";
import { NarrativeStrip } from "./NarrativeStrip";

interface Props {
  section: Section;
}

const LINE_COLOR = "#7e9ad4"; // strata-macro

type MacroUnit = "%" | "index" | "thousands" | "$M" | "$/bbl";

/** Units per series label, mirroring app/services/macro.py. */
const UNIT_BY_LABEL: Record<string, MacroUnit> = {
  "10Y Treasury yield": "%",
  "2Y Treasury yield": "%",
  "Unemployment rate": "%",
  "Consumer price index": "index",
  "Consumer sentiment": "index",
  "Manufacturing employment": "thousands",
  "Retail sales": "$M",
  "WTI crude oil price": "$/bbl",
  "Brent crude oil price": "$/bbl",
};

export function formatMacroValue(v: number, unit: MacroUnit | undefined): string {
  switch (unit) {
    case "%":
      return `${v.toFixed(2)}%`;
    case "$/bbl":
      return `$${v.toFixed(2)}`;
    case "thousands":
      return `${(v / 1000).toFixed(2)}M`;
    case "$M":
      return `$${(v / 1000).toFixed(1)}B`;
    default:
      return Math.abs(v) >= 100 ? v.toFixed(0) : v.toFixed(1);
  }
}

/** "2024-04" → "Apr '24"; other shapes pass through. */
function monthLabel(period: string): string {
  const m = /^(\d{4})-(\d{2})/.exec(period);
  if (!m) return period;
  const month = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, 1)).toLocaleDateString("en-US", {
    month: "short",
    timeZone: "UTC",
  });
  return `${month} '${m[1].slice(2)}`;
}

/** Change across the window: points for a rate, percent otherwise. */
export function macroChange(history: ClaimHistoryPoint[], unit: MacroUnit | undefined): string | null {
  const h = [...history].sort((a, b) => (a.period < b.period ? -1 : 1));
  if (h.length < 2) return null;
  const first = h[0];
  const last = h[h.length - 1];
  const since = `since ${monthLabel(first.period)}`;
  if (unit === "%") {
    const pts = last.value - first.value;
    return `${pts >= 0 ? "+" : "−"}${Math.abs(pts).toFixed(2)} pts ${since}`;
  }
  if (first.value === 0) return null;
  const pct = (last.value / first.value - 1) * 100;
  return `${pct >= 0 ? "+" : "−"}${Math.abs(pct).toFixed(1)}% ${since}`;
}

function toChartData(history: ClaimHistoryPoint[]) {
  return [...history]
    .sort((a, b) => (a.period < b.period ? -1 : 1))
    .map((p) => ({ ts: p.period, close: p.value }));
}

function Panel({ panel }: { panel: MacroPanelSpec }) {
  const unit = UNIT_BY_LABEL[panel.label];
  const change = macroChange(panel.history, unit);
  return (
    <div data-testid="macro-panel" className="rounded-md bg-strata-raise px-3 py-3">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-xs text-strata-fg">{panel.label}</span>
        <span className="font-mono text-base font-medium text-strata-hi">{formatMacroValue(panel.latest, unit)}</span>
      </div>
      {change && <div className="mb-1 text-right font-mono text-[11px] text-strata-dim">{change}</div>}
      <LineChart
        data={toChartData(panel.history)}
        width={280}
        height={72}
        strokeColor={LINE_COLOR}
        strokeWidth={1.75}
        showAxes
        showTooltip
        formatValue={(v) => formatMacroValue(v, unit)}
        ariaLabel={`${panel.label} by month`}
      />
    </div>
  );
}

export function MacroPanel({ section }: Props) {
  const panels = extractMacroPanels(section);

  if (panels.length === 0) {
    return null;
  }

  return (
    <section className="flex h-full flex-col rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-macro">
        Macro · FRED
      </div>

      <div className="flex flex-col gap-3">
        {panels.map((panel) => (
          <Panel key={panel.label} panel={panel} />
        ))}
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
