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
  extractRiskDiffBars,
  extractRiskDiffSummary,
  type RiskDiffBars,
} from "../lib/risk-extract";
import type { Section } from "../lib/schemas";

interface Props {
  section: Section;
}

const COLOR_RISK = "#e57c6e";
const COLOR_QUAL = "#7ad0a6";
const COLOR_DIM = "#5a6473";
const COLOR_HI = "#f5f7fb";

interface BarRow {
  label: string;
  value: number;
  color: string;
}

function buildRows(bars: RiskDiffBars): BarRow[] {
  return [
    { label: "Added", value: bars.added, color: COLOR_RISK },
    { label: "Removed", value: bars.removed, color: COLOR_QUAL },
    { label: "Kept", value: bars.kept, color: COLOR_DIM },
    { label: "Char delta", value: bars.charDelta, color: COLOR_HI },
  ];
}

function frameWord(framing: "expanded" | "shrank" | "stable"): string {
  if (framing === "expanded") return "Disclosure expanded.";
  if (framing === "shrank") return "Disclosure shrank.";
  return "Disclosure stable.";
}

function formatNetDelta(n: number): string {
  if (n > 0) return `+${n} ¶`;
  if (n < 0) return `${n} ¶`;
  return "0 ¶";
}

const W = 360;
const H = 132;
const ROW_GAP = 8;
const LABEL_W = 80;
const VALUE_W = 56;
const BAR_X = LABEL_W;
const BAR_W = W - LABEL_W - VALUE_W;
const ROW_H = (H - ROW_GAP * 3) / 4;

export function RiskDiffCard({ section }: Props) {
  const bars = extractRiskDiffBars(section);
  const summary = extractRiskDiffSummary(section);

  if (!bars || !summary) {
    return (
      <section className="rounded-md border border-strata-border bg-strata-surface p-5">
        <div className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-risk">
          10-K risk diff · vs prior
        </div>
        <div className="flex h-[120px] items-center justify-center font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
          Risk diff unavailable
        </div>
      </section>
    );
  }

  const rows = buildRows(bars);
  // Normalize bar widths to the absolute max value across rows so the
  // visual scale is consistent. Char delta dwarfs paragraph counts;
  // we keep them on separate scales by computing two scales: paragraphs
  // scale on rows[0..2], char delta solo. Simpler: |max|-relative width
  // per row, all on a 0..1 fraction of BAR_W with abs value mapping.
  const paraMax = Math.max(bars.added, bars.removed, bars.kept) || 1;
  const charScale = Math.abs(bars.charDelta) || 1;

  function barLength(row: BarRow): number {
    if (row.label === "Char delta") {
      return (Math.abs(row.value) / charScale) * BAR_W;
    }
    return (Math.abs(row.value) / paraMax) * BAR_W;
  }

  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-3 flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-risk">
          10-K risk diff · vs prior
        </div>
      </div>

      <svg
        data-testid="risk-diff-bars"
        width={W}
        height={H}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Risk diff bars"
        className="block"
      >
        {rows.map((row, i) => {
          const y = i * (ROW_H + ROW_GAP);
          const barLen = Math.max(2, barLength(row));
          return (
            <g key={row.label} data-row="risk-diff-bar">
              <text
                x={0}
                y={y + ROW_H / 2 + 4}
                fill={COLOR_DIM}
                style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)" }}
              >
                {row.label}
              </text>
              <rect
                x={BAR_X}
                y={y + ROW_H / 4}
                width={barLen}
                height={ROW_H / 2}
                fill={row.color}
                rx={2}
              />
              <text
                x={W}
                y={y + ROW_H / 2 + 4}
                fill={COLOR_HI}
                textAnchor="end"
                style={{
                  fontSize: 11,
                  fontFamily: "var(--font-mono, monospace)",
                  fontWeight: 500,
                }}
              >
                {row.value > 0 && row.label === "Char delta" ? `+${row.value}` : row.value}
              </text>
            </g>
          );
        })}
      </svg>

      <div className="mt-3 rounded-md bg-strata-raise px-3 py-2 text-xs leading-relaxed text-strata-dim">
        <span className="text-strata-fg">{frameWord(summary.framing)}</span>{" "}
        Net{" "}
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
        </span>{" "}
        ({bars.added} added · {bars.removed} dropped · {bars.kept} kept).
      </div>
    </section>
  );
}
