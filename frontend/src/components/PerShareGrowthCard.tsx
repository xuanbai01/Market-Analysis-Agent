/**
 * PerShareGrowthCard — Phase 4.3.A.
 *
 * Renders the row-3 card from `direction-strata.jsx`: 5 per-share
 * series rebased to first-point=100, plotted on a shared MultiLine,
 * with 5 multiplier pills below summarizing total growth.
 *
 * Data lives in the Quality section (history-bearing claims from
 * Phase 3.2.A). The card is read-only — no toggle, no expand. The
 * deeper claim list still surfaces in QualityCard's hybrid table
 * above this card; PerShareGrowthCard is the visual companion.
 */
import {
  extractGrowthCagr,
  extractGrowthMultipliers,
  extractGrowthSeries,
  type GrowthMultipliers,
} from "../lib/growth-extract";
import type { Section } from "../lib/schemas";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { MultiLine } from "./MultiLine";

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

export function PerShareGrowthCard({ ticker, section }: Props) {
  const series = extractGrowthSeries(section);
  const mults = extractGrowthMultipliers(section);
  const cagrs = extractGrowthCagr(section);
  const periodLength = series[0]?.history.length ?? 0;

  return (
    // No mb-6 — vertical spacing comes from the parent grid's gap-6.
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-growth">
            Per-share growth · {ticker} · rebased first = 100
          </div>
          {/*
            Phase 4.3.X (Bug 5) — narrative strip removed. PerShareGrowthCard
            and QualityCard both read from the Quality section; rendering
            section.summary here produced visible duplication of the prose.
            Per-card narratives come back in 4.4 as a card-specific field
            (``card_summary``) wired by the orchestrator. Until then, the
            multipliers (RV / GP / OpI / FCF / OCF) are the message.
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

      {series.length >= 2 ? (
        <MultiLine series={series} height={200} />
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
    </section>
  );
}
