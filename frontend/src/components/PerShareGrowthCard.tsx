/**
 * PerShareGrowthCard — Phase 4.3.A; redrawn 2026-11; ten years 2026-11.
 *
 * Two views of per-share growth, toggled in the header:
 *
 *   10Y (default when SEC data exists) — up to eleven annual points from
 *   10-K filings (app/services/annual_history.py, split-adjusted): a
 *   revenue + operating income panel and an EPS + FCF panel, each on its
 *   own labelled scale (EPS sits at a fraction of revenue per share and
 *   would flatten on a shared one). Pills give each series' multiple and
 *   compound annual rate over its span, or the dollar move when an end
 *   is a loss.
 *
 *   5Q — the yfinance quarterly series (Revenue, Gross profit, Op
 *   income, OCF, FCF) on one shared scale, pills giving year-over-year
 *   change (same quarter, a year apart). This was the only view until
 *   SEC history landed: five quarters could say "+7.4% YoY" but nothing
 *   about compounding.
 *
 * Until 2026-11 the quarterly view was one chart of all five lines
 * rebased to the first quarter = 100, with no axis or baseline and
 * smoothed curves (tasks/dogfood-2026-11.md #8). Rebasing inflated small
 * bases and flipped negative ones; the series share a unit, so they plot
 * as-is and the growth story lives in the pills.
 *
 * Data lives in the Quality section.
 */
import { useState } from "react";

import { relativeChange, usdPerShare, usdTick } from "../lib/chart-format";
import {
  ANNUAL_SPEC,
  extractAnnualPanels,
  extractGrowthChanges,
  extractLongTermGrowth,
  extractPerSharePanels,
  type GrowthChange,
  type GrowthKey,
  type LongTermGrowth,
} from "../lib/growth-extract";
import type { Section } from "../lib/schemas";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { MultiLine, type MultiLineSeries } from "./MultiLine";
import { NarrativeStrip } from "./NarrativeStrip";

interface Props {
  ticker: string;
  section: Section;
}

type View = "annual" | "quarterly";

const COLOR_VAL = "#6cb6ff";
const COLOR_QUAL = "#7ad0a6";
const COLOR_CASH = "#e8c277";
const COLOR_EARN = "#d68dc6";
const COLOR_DIM = "#8892a0";

const PILL_SPEC: { key: GrowthKey; label: string; color: string }[] = [
  { key: "rev", label: "Rev", color: COLOR_VAL },
  { key: "gp", label: "GP", color: COLOR_QUAL },
  { key: "opi", label: "OpI", color: COLOR_CASH },
  { key: "fcf", label: "FCF", color: COLOR_EARN },
  { key: "ocf", label: "OCF", color: COLOR_DIM },
];

function formatChange(c: GrowthChange | null): string {
  if (c === null || !Number.isFinite(c.value)) return "—";
  if (c.kind === "usd") return signedUsd(c.value);
  const pct = c.value * 100;
  const digits = Math.abs(pct) >= 100 ? 0 : 1;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(digits)}%`;
}

function signedUsd(v: number): string {
  return `${v >= 0 ? "+" : "-"}${usdPerShare(Math.abs(v))}`;
}

/** 3.1× / 40× / 0.8× */
function formatMultiple(m: number): string {
  return `${m >= 10 ? m.toFixed(0) : m.toFixed(1)}×`;
}

/** +12.0% / yr */
function formatRate(r: number): string {
  const pct = r * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}% / yr`;
}

const PANEL_HEIGHT = 190;
const quarterChange = relativeChange(usdPerShare, "QoQ");
const yearChange = relativeChange(usdPerShare, "YoY");

function Panel({
  testId,
  title,
  series,
  domain,
  change,
}: {
  testId: string;
  title: string;
  series: MultiLineSeries[];
  domain?: [number, number];
  change: (now: number, prev: number) => string;
}) {
  return (
    <div data-testid={testId}>
      <div className="mb-1 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
        {title}
      </div>
      <MultiLine
        series={series}
        width={300}
        height={PANEL_HEIGHT}
        yDomain={domain}
        includeZero
        formatValue={usdPerShare}
        formatTick={usdTick}
        formatChange={change}
        ariaLabel={`${title}: ${series.map((s) => s.label).join(", ")}`}
      />
    </div>
  );
}

function ViewToggle({
  view,
  onChange,
  annualLabel,
  quarterlyLabel,
}: {
  view: View;
  onChange: (v: View) => void;
  annualLabel: string;
  quarterlyLabel: string;
}) {
  const options: { id: View; label: string; title: string }[] = [
    { id: "annual", label: annualLabel, title: "Annual, from SEC filings" },
    { id: "quarterly", label: quarterlyLabel, title: "Quarterly, latest quarters" },
  ];
  return (
    <div role="group" aria-label="Per-share history span" className="flex gap-1 font-mono text-xs">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          data-view={o.id}
          title={o.title}
          aria-pressed={o.id === view}
          onClick={() => onChange(o.id)}
          className={`rounded px-2 py-0.5 transition ${
            o.id === view ? "bg-strata-highlight text-strata-canvas" : "text-strata-dim hover:text-strata-fg"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function AnnualPill({ label, color, g }: { label: string; color: string; g: LongTermGrowth }) {
  const shrinking = g.multiple !== null ? g.multiple < 1 : g.change < 0;
  return (
    <div data-pill="growth-annual" className="min-w-[6rem] flex-1 rounded-md bg-strata-raise px-3 py-2">
      <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-kicker text-strata-dim">
        <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-sm" style={{ backgroundColor: color }} />
        {label}
      </div>
      <div className={`mt-1 font-mono text-base font-medium ${shrinking ? "text-strata-neg" : "text-strata-hi"}`}>
        {g.multiple !== null ? formatMultiple(g.multiple) : signedUsd(g.change)}
      </div>
      {/* A rate of a loss misleads: with a non-positive end the pill
          shows the two ends instead. */}
      <div className="mt-0.5 font-mono text-[11px] text-strata-fg">
        {g.cagr !== null ? formatRate(g.cagr) : `${usdPerShare(g.firstValue)} → ${usdPerShare(g.lastValue)}`}
      </div>
      <div data-testid="growth-basis" className="mt-0.5 font-mono text-[10px] text-strata-dim">
        {g.firstPeriod} → {g.lastPeriod}
      </div>
    </div>
  );
}

export function PerShareGrowthCard({ ticker, section }: Props) {
  const panels = extractPerSharePanels(section);
  const changes = extractGrowthChanges(section);
  const annual = extractAnnualPanels(section);
  const longTerm = extractLongTermGrowth(section);

  const quarterly = [...panels.income, ...panels.cashFlow];
  const annualSeries = [...annual.topLine, ...annual.earnings];
  const hasAnnual = annualSeries.length > 0;
  const hasQuarterly = quarterly.length > 0;
  const [chosen, setChosen] = useState<View>(hasAnnual ? "annual" : "quarterly");
  const view: View = !hasAnnual ? "quarterly" : !hasQuarterly ? "annual" : chosen;

  const quarters = Math.max(0, ...quarterly.map((s) => s.history.length));
  const years = Math.max(0, ...Object.values(longTerm).map((g) => g?.years ?? 0));
  const quarterlyLabel = `${quarters}Q`;
  const annualLabel = `${years}Y`;

  const values = quarterly.flatMap((s) => s.history.map((p) => p.value));
  // Quarterly: one scale for both panels so a cash-flow line and an
  // income line of the same height mean the same $/share.
  const domain: [number, number] = [Math.min(0, ...values), Math.max(0, ...values)];

  return (
    // No mb-6 — vertical spacing comes from the parent grid's gap-6.
    <section className="flex h-full flex-col rounded-md border border-strata-border bg-strata-surface p-5">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-growth">
          Per-share growth · {ticker} · $ / share
        </div>
        <div className="flex items-center gap-3">
          {hasAnnual && hasQuarterly ? (
            <ViewToggle view={view} onChange={setChosen} annualLabel={annualLabel} quarterlyLabel={quarterlyLabel} />
          ) : (
            (hasAnnual || quarters > 0) && (
              <span className="font-mono text-[10px] uppercase tracking-kicker text-strata-dim">
                {hasAnnual ? annualLabel : quarterlyLabel}
              </span>
            )
          )}
          <ConfidenceBadge confidence={section.confidence} size="sm" />
        </div>
      </header>

      {view === "annual" ? (
        <>
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            {annual.topLine.length > 0 && (
              <Panel
                testId="per-share-panel-topline"
                title="Revenue & op income / share"
                series={annual.topLine}
                change={yearChange}
              />
            )}
            {annual.earnings.length > 0 && (
              <Panel
                testId="per-share-panel-earnings"
                title="EPS & FCF / share"
                series={annual.earnings}
                change={yearChange}
              />
            )}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            {ANNUAL_SPEC.map((spec) => {
              const g = longTerm[spec.key];
              return g ? <AnnualPill key={spec.key} label={spec.shortLabel} color={spec.color} g={g} /> : null;
            })}
          </div>
          <p className="mt-2 font-mono text-[10px] text-strata-muted">
            Annual 10-K figures from SEC filings · calendar years · split-adjusted
          </p>
        </>
      ) : (
        <>
          {hasQuarterly ? (
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
              {panels.income.length > 0 && (
                <Panel
                  testId="per-share-panel-income"
                  title="Income / share"
                  series={panels.income}
                  domain={domain}
                  change={quarterChange}
                />
              )}
              {panels.cashFlow.length > 0 && (
                <Panel
                  testId="per-share-panel-cashflow"
                  title="Cash flow / share"
                  series={panels.cashFlow}
                  domain={domain}
                  change={quarterChange}
                />
              )}
            </div>
          ) : (
            <div className="flex h-[120px] items-center justify-center font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
              Per-share growth history unavailable
            </div>
          )}

          <div className="mt-4 grid grid-cols-5 gap-2">
            {PILL_SPEC.map((spec) => {
              const c = changes[spec.key];
              return (
                <div key={spec.key} data-pill="growth-change" className="rounded-md bg-strata-raise px-3 py-2">
                  <div className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-kicker text-strata-dim">
                    <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-sm" style={{ backgroundColor: spec.color }} />
                    {spec.label}
                  </div>
                  <div
                    className={`mt-1 font-mono text-base font-medium ${
                      c && c.value < 0 ? "text-strata-neg" : "text-strata-hi"
                    }`}
                  >
                    {formatChange(c)}
                  </div>
                  <div data-testid="growth-basis" className="mt-0.5 font-mono text-[10px] text-strata-dim">
                    {c ? (c.yearOverYear ? "YoY" : c.basis) : "—"}
                  </div>
                </div>
              );
            })}
          </div>
          {Object.values(changes).some((c) => c?.yearOverYear) && (
            <p className="mt-2 font-mono text-[10px] text-strata-muted">
              YoY: {Object.values(changes).find((c) => c?.yearOverYear)?.basis}
            </p>
          )}
        </>
      )}

      <NarrativeStrip text={section.card_narrative} />
    </section>
  );
}
