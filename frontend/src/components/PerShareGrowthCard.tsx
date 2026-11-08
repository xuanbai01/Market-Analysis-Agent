/**
 * PerShareGrowthCard — Phase 4.3.A; redrawn 2026-11.
 *
 * Five per-share series (Revenue, Gross profit, Op income, OCF, FCF) as
 * actual dollars per share in two panels — income lines and cash-flow
 * lines — on one shared, labelled scale, with 5 multiplier + CAGR pills
 * below summarizing total growth.
 *
 * Until 2026-11 this was one chart of all five lines rebased to the
 * first quarter = 100, with no axis or baseline and smoothed curves
 * (tasks/dogfood-2026-11.md #8). Rebasing inflated small bases and
 * flipped negative ones; the series share a unit, so they now plot as-is
 * and the growth story lives in the pills.
 *
 * Data lives in the Quality section (history-bearing claims from
 * Phase 3.2.A).
 */
import { relativeChange, usdPerShare, usdTick } from "../lib/chart-format";
import {
  extractGrowthCagr,
  extractGrowthMultipliers,
  extractPerSharePanels,
  type GrowthMultipliers,
} from "../lib/growth-extract";
import type { Section } from "../lib/schemas";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { MultiLine, type MultiLineSeries } from "./MultiLine";
import { NarrativeStrip } from "./NarrativeStrip";

interface Props {
  ticker: string;
  section: Section;
}

const COLOR_VAL = "#6cb6ff";
const COLOR_QUAL = "#7ad0a6";
const COLOR_CASH = "#e8c277";
const COLOR_EARN = "#d68dc6";
const COLOR_DIM = "#8892a0";

const PILL_SPEC: { key: keyof GrowthMultipliers; label: string; color: string }[] = [
  { key: "rev", label: "Rev", color: COLOR_VAL },
  { key: "gp", label: "GP", color: COLOR_QUAL },
  { key: "opi", label: "OpI", color: COLOR_CASH },
  { key: "fcf", label: "FCF", color: COLOR_EARN },
  { key: "ocf", label: "OCF", color: COLOR_DIM },
];

function formatMultiplier(n: number | null): string {
  if (n === null || !Number.isFinite(n)) return "—";
  return `${n.toFixed(1)}×`;
}

function formatCagr(n: number | null): string {
  // Phase 4.3.B.1 — per-period CAGR rendered as a signed percent.
  // The sub-line beneath each multiplier pill conveys per-quarter
  // growth pace alongside the total-period multiplier.
  if (n === null || !Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${(n * 100).toFixed(1)}%`;
}

const PANEL_HEIGHT = 190;
const perShareChange = relativeChange(usdPerShare);

function Panel({
  testId,
  title,
  series,
  domain,
}: {
  testId: string;
  title: string;
  series: MultiLineSeries[];
  domain: [number, number];
}) {
  return (
    <div data-testid={testId}>
      <div className="mb-1 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
        {title}
      </div>
      <MultiLine
        series={series}
        width={320}
        height={PANEL_HEIGHT}
        yDomain={domain}
        includeZero
        formatValue={usdPerShare}
        formatTick={usdTick}
        formatChange={perShareChange}
        ariaLabel={`${title}: ${series.map((s) => s.label).join(", ")}`}
      />
    </div>
  );
}

export function PerShareGrowthCard({ ticker, section }: Props) {
  const panels = extractPerSharePanels(section);
  const mults = extractGrowthMultipliers(section);
  const cagrs = extractGrowthCagr(section);
  const all = [...panels.income, ...panels.cashFlow];
  const periodLength = Math.max(0, ...all.map((s) => s.history.length));
  const values = all.flatMap((s) => s.history.map((p) => p.value));
  // One scale for both panels so a cash-flow line and an income line of
  // the same height mean the same $/share.
  const domain: [number, number] = [Math.min(0, ...values), Math.max(0, ...values)];

  return (
    // No mb-6 — vertical spacing comes from the parent grid's gap-6.
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-growth">
            Per-share growth · {ticker} · $ / share
          </div>
          {/*
            Phase 4.4.B — per-card narrative slot returns at the bottom
            of the card body via NarrativeStrip. The header stays clean;
            the strip below carries the LLM's "Revenue compounds; profit
            doesn't" framing on a Quality-section card_narrative now
            distinct from QualityCard's surface (no more duplication).
          */}
        </div>
        <div className="flex items-center gap-3">
          {periodLength > 0 && (
            <span className="font-mono text-[10px] uppercase tracking-kicker text-strata-dim">
              {periodLength}Q
            </span>
          )}
          <ConfidenceBadge confidence={section.confidence} size="sm" />
        </div>
      </header>

      {all.length > 0 ? (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          {panels.income.length > 0 && (
            <Panel testId="per-share-panel-income" title="Income / share" series={panels.income} domain={domain} />
          )}
          {panels.cashFlow.length > 0 && (
            <Panel testId="per-share-panel-cashflow" title="Cash flow / share" series={panels.cashFlow} domain={domain} />
          )}
        </div>
      ) : (
        <div className="flex h-[120px] items-center justify-center font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
          Per-share growth history unavailable
        </div>
      )}

      <div className="mt-4 grid grid-cols-5 gap-2">
        {PILL_SPEC.map((spec) => (
          <div
            key={spec.key}
            data-pill="growth-multiplier"
            className="rounded-md bg-strata-raise px-3 py-2"
          >
            <div
              className="font-mono text-[9px] uppercase tracking-kicker"
              style={{ color: spec.color }}
            >
              {spec.label}
            </div>
            <div className="mt-1 font-mono tabular text-base font-medium text-strata-hi">
              {formatMultiplier(mults[spec.key])}
            </div>
            <div
              data-testid="growth-cagr"
              className="mt-0.5 font-mono text-[10px] tabular text-strata-dim"
            >
              {formatCagr(cagrs[spec.key])} / Q
            </div>
          </div>
        ))}
      </div>

      <NarrativeStrip text={section.card_narrative} />
    </section>
  );
}
