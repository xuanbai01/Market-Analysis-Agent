/**
 * ValuationHistory — the company's own multiples at each fiscal
 * year-end, with today's reading at the end of the line (2026-11).
 *
 * One small chart per multiple (P/E, price / sales, price / free cash
 * flow), each on its own scale: the three are different measures, so
 * they don't share an axis or hide behind a selector. Each chart is one
 * line; its title names it, so there is no legend. The reference line is
 * the median of the year-ends, and the sentence above the chart states
 * today, the median and the gap between them, so the reading doesn't
 * depend on the picture.
 *
 * The year-end points are fiscal-year figures from SEC filings; today's
 * point is the trailing-twelve-month multiple. The note under the
 * charts says so. Above or below the median is not coloured as good or
 * bad: it is a position, not a verdict.
 */
import type { OwnHistoryPanel } from "../lib/valuation-history-extract";
import { MultiLine } from "./MultiLine";

const LINE_COLOR = "#6cb6ff"; // strata-valuation
const PANEL_HEIGHT = 150;
const TODAY = "Today";

const multiple = (v: number) => `${v.toFixed(1)}×`;

/** "100% above" / "10% below" / "in line with"; null without a gap. */
function gapText(premium: number | null): string | null {
  if (premium === null) return null;
  const pct = Math.round(Math.abs(premium) * 100);
  if (pct === 0) return "in line with it";
  return `${pct}% ${premium > 0 ? "above" : "below"}`;
}

function readText(panel: OwnHistoryPanel): string {
  const today = panel.today !== null ? `Today ${multiple(panel.today)}` : "No trailing figure today";
  if (panel.median === null) {
    return `${today} · ${panel.history.length} year-ends, too few for a median`;
  }
  const gap = gapText(panel.premium);
  return [today, `median ${multiple(panel.median)}`, gap].filter(Boolean).join(" · ");
}

function Panel({ panel }: { panel: OwnHistoryPanel }) {
  const history =
    panel.today !== null ? [...panel.history, { period: TODAY, value: panel.today }] : panel.history;
  const last = history[history.length - 1].period;
  return (
    <div data-testid="own-history-panel" data-multiple={panel.key}>
      <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-valuation">{panel.label}</div>
      <div data-testid="own-history-read" className="mb-1 mt-0.5 font-mono text-[11px] text-strata-dim">
        {readText(panel)}
      </div>
      <MultiLine
        series={[{ label: panel.label, shortLabel: last, color: LINE_COLOR, history }]}
        width={340}
        height={PANEL_HEIGHT}
        showLegend={false}
        baseline={panel.median ?? undefined}
        formatValue={multiple}
        formatTick={(v) => String(Number(v.toFixed(1)))}
        formatPeriod={(period) => period}
        ariaLabel={`${panel.label} at each fiscal year-end${panel.today !== null ? ", then today" : ""}`}
      />
    </div>
  );
}

interface Props {
  panels: OwnHistoryPanel[];
}

export function ValuationHistory({ panels }: Props) {
  if (panels.length === 0) return null;
  const hasMedian = panels.some((p) => p.median !== null);
  return (
    <div data-testid="own-history" className="mt-6 border-t border-strata-line pt-5">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
        Against its own history
      </div>
      <div className="grid grid-cols-1 gap-x-8 gap-y-5 md:grid-cols-2 xl:grid-cols-3">
        {panels.map((panel) => (
          <Panel key={panel.key} panel={panel} />
        ))}
      </div>
      <p data-testid="own-history-note" className="mt-3 font-mono text-[10px] text-strata-muted">
        {hasMedian && (
          <>
            <span aria-hidden="true" className="mr-1.5 inline-block h-px w-4 bg-strata-muted align-middle" />
            median of the year-ends ·{" "}
          </>
        )}
        each point is the fiscal year-end close over that year&apos;s figure from SEC filings · today is the
        trailing 12 months · loss years are left out
      </p>
    </div>
  );
}
