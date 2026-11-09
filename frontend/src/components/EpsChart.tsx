/**
 * EpsChart — quarterly EPS, actual against consensus, as dots on a
 * dollar axis. Replaces EpsBars (2026-11 chart audit): the bars had no
 * axis or quarter labels, the consensus was a grey tick laid over each
 * bar, and for loss-makers a "beat" was a green bar hanging below zero.
 *
 *   - Consensus: a hollow ring. Actual: a filled dot, green when it met
 *     or beat consensus, red when it missed (neutral without one). A
 *     hairline joins the two, so the gap is the surprise.
 *   - Dollar axis with clean ticks; a zero line when EPS crosses zero.
 *   - Quarter axis: each year's first quarter plus the latest.
 *   - Hover a quarter for actual, consensus and surprise; the card's
 *     recent-prints table repeats the latest four in text.
 *   - Drawn at the container's measured width so text stays 11 px.
 */
import { useState } from "react";

import { shortPeriod, usdPerShare, usdTick } from "../lib/chart-format";
import type { ClaimHistoryPoint } from "../lib/schemas";
import { useMeasuredWidth } from "../lib/use-measured-width";
import { niceTicks } from "./MultiLine";

interface Props {
  actual: ClaimHistoryPoint[];
  estimate: ClaimHistoryPoint[];
  /** Fallback width before measurement (and in tests). */
  width?: number;
  height?: number;
}

const DEFAULT_WIDTH = 560;
const DEFAULT_HEIGHT = 190;
const PAD_TOP = 10;
const PAD_BOTTOM = 22;
const PAD_RIGHT = 12;
const CHAR_W = 6.7; // ~11 px mono glyph in px
const DOT_R = 4.5;

const POS = "#5fbf8a"; // strata-pos
const NEG = "#e57c6e"; // strata-neg
const NEUTRAL = "#8892a0"; // strata-dim
const RING = "#8892a0"; // strata-dim
const SURFACE = "#0e1116"; // strata-surface
const GRID = "#1f2630"; // strata-line
const CONNECTOR = "#3a4452";
const AXIS_TEXT = "#5a6473"; // strata-muted
const ZERO_LINE = "#5a6473";
const LABEL_STYLE = { fontSize: 11, fontFamily: "var(--font-mono, monospace)" };

function surprisePct(actual: number, estimate: number): number | null {
  if (estimate === 0) return null;
  return ((actual - estimate) / Math.abs(estimate)) * 100;
}

/** Each year's first quarter plus the latest, dropping any label that
 *  would sit closer than ``minGap`` slots to the one after it. */
function xTickIndices(periods: string[], minGap: number): number[] {
  const last = periods.length - 1;
  const candidates = periods
    .map((p, i) => (/-Q1$/.test(p) || i === last ? i : -1))
    .filter((i) => i >= 0);
  const kept: number[] = [];
  for (let k = candidates.length - 1; k >= 0; k--) {
    const i = candidates[k];
    if (kept.length === 0 || kept[0] - i >= minGap) kept.unshift(i);
  }
  return kept;
}

export function EpsChart({ actual, estimate, width = DEFAULT_WIDTH, height = DEFAULT_HEIGHT }: Props) {
  const [measureRef, measured] = useMeasuredWidth();
  const [hover, setHover] = useState<number | null>(null);
  if (actual.length === 0) return null;

  const points = [...actual].sort((a, b) => (a.period < b.period ? -1 : 1));
  const estByPeriod = new Map(estimate.map((e) => [e.period, e.value]));
  const rows = points.map((p) => {
    const est = estByPeriod.get(p.period);
    const result = est === undefined ? null : p.value >= est ? "beat" : "miss";
    return { period: p.period, actual: p.value, estimate: est ?? null, result };
  });
  const hasEstimates = rows.some((r) => r.estimate !== null);

  const values = rows.flatMap((r) => (r.estimate === null ? [r.actual] : [r.actual, r.estimate]));
  const ticks = niceTicks(Math.min(...values), Math.max(...values));
  const yLo = ticks[0];
  const yHi = ticks[ticks.length - 1];
  const tickLabels = ticks.map(usdTick);

  const W = measured ?? width;
  const padLeft = 10 + Math.max(...tickLabels.map((t) => t.length)) * CHAR_W;
  const innerW = Math.max(1, W - padLeft - PAD_RIGHT);
  const plotBottom = height - PAD_BOTTOM;
  const slot = innerW / rows.length;
  const xAt = (i: number) => padLeft + (i + 0.5) * slot;
  const yOf = (v: number) => PAD_TOP + (1 - (v - yLo) / (yHi - yLo || 1)) * (plotBottom - PAD_TOP);

  const labelPx = 6 * CHAR_W;
  const xTicks = xTickIndices(
    rows.map((r) => r.period),
    Math.max(1, Math.ceil((labelPx + 8) / slot)),
  );
  const clampLabelX = (x: number) => Math.min(Math.max(x, padLeft + labelPx / 2), W - labelPx / 2);

  const hovered = hover === null ? null : rows[hover];
  const hoverLeftPct = hover === null ? 0 : (xAt(hover) / W) * 100;

  return (
    <div>
      <div className="relative" ref={measureRef}>
        <svg
          data-testid="eps-chart"
          width="100%"
          height={height}
          viewBox={`0 0 ${W} ${height}`}
          role="img"
          aria-label={`Quarterly EPS, actual against consensus, ${shortPeriod(rows[0].period)} to ${shortPeriod(rows[rows.length - 1].period)}`}
          className="block"
        >
          {ticks.map((t, i) => (
            <g key={t}>
              {t !== 0 && <line x1={padLeft} x2={W - PAD_RIGHT} y1={yOf(t)} y2={yOf(t)} stroke={GRID} strokeWidth={1} />}
              <text data-testid="eps-y-tick" x={padLeft - 6} y={yOf(t) + 3.5} textAnchor="end" fill={AXIS_TEXT} style={LABEL_STYLE}>
                {tickLabels[i]}
              </text>
            </g>
          ))}
          {yLo < 0 && yHi > 0 && (
            <line data-testid="eps-zero-line" x1={padLeft} x2={W - PAD_RIGHT} y1={yOf(0)} y2={yOf(0)} stroke={ZERO_LINE} strokeWidth={1} />
          )}

          {xTicks.map((i) => (
            <text
              key={rows[i].period}
              data-testid="eps-x-tick"
              x={clampLabelX(xAt(i))}
              y={height - 6}
              textAnchor="middle"
              fill={AXIS_TEXT}
              style={LABEL_STYLE}
            >
              {shortPeriod(rows[i].period)}
            </text>
          ))}

          {hover !== null && (
            <rect x={xAt(hover) - slot / 2} y={PAD_TOP} width={slot} height={plotBottom - PAD_TOP} fill="#ffffff" opacity={0.04} />
          )}

          {rows.map((r, i) => {
            const x = xAt(i);
            const fill = r.result === "beat" ? POS : r.result === "miss" ? NEG : NEUTRAL;
            return (
              <g key={r.period}>
                {r.estimate !== null && (
                  <>
                    <line x1={x} x2={x} y1={yOf(r.estimate)} y2={yOf(r.actual)} stroke={CONNECTOR} strokeWidth={1} />
                    <circle
                      data-mark="estimate"
                      cx={x}
                      cy={yOf(r.estimate)}
                      r={DOT_R - 0.5}
                      fill={SURFACE}
                      stroke={RING}
                      strokeWidth={1.5}
                    />
                  </>
                )}
                <circle
                  data-mark="actual"
                  data-result={r.result ?? undefined}
                  cx={x}
                  cy={yOf(r.actual)}
                  r={DOT_R}
                  fill={fill}
                  stroke={SURFACE}
                  strokeWidth={2}
                />
              </g>
            );
          })}

          {/* Hit areas: one full-height column per quarter. */}
          {rows.map((r, i) => (
            <rect
              key={r.period}
              data-testid="eps-hit"
              x={xAt(i) - slot / 2}
              y={PAD_TOP}
              width={slot}
              height={plotBottom - PAD_TOP}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
              onMouseLeave={() => setHover(null)}
            />
          ))}
        </svg>

        {hovered && (
          <div
            data-testid="eps-tooltip"
            className="pointer-events-none absolute top-0 z-10 rounded-md border border-strata-border bg-strata-raise px-2.5 py-1.5 font-mono text-[11px] text-strata-fg shadow-sm"
            style={{
              left: `${hoverLeftPct}%`,
              transform: hoverLeftPct > 55 ? "translateX(calc(-100% - 10px))" : "translateX(10px)",
            }}
          >
            <div className="mb-0.5 text-strata-dim">{shortPeriod(hovered.period)}</div>
            <div className="whitespace-nowrap">
              <span className="text-strata-dim">Actual </span>
              <span className="tabular text-strata-hi">{usdPerShare(hovered.actual)}</span>
            </div>
            {hovered.estimate !== null && (
              <>
                <div className="whitespace-nowrap">
                  <span className="text-strata-dim">Consensus </span>
                  <span className="tabular text-strata-hi">{usdPerShare(hovered.estimate)}</span>
                </div>
                {surprisePct(hovered.actual, hovered.estimate) !== null && (
                  <div className="whitespace-nowrap">
                    <span className="text-strata-dim">Surprise </span>
                    <span className="tabular text-strata-hi">
                      {(() => {
                        const s = surprisePct(hovered.actual, hovered.estimate as number) as number;
                        return `${s >= 0 ? "+" : ""}${s.toFixed(1)}%`;
                      })()}
                    </span>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>

      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-mono text-[11px] text-strata-dim">
        {hasEstimates ? (
          <>
            <LegendDot color={POS} label="Beat" />
            <LegendDot color={NEG} label="Miss" />
            <span className="inline-flex items-center gap-1.5">
              <svg width="10" height="10" aria-hidden="true">
                <circle cx="5" cy="5" r="3.5" fill="none" stroke={RING} strokeWidth="1.5" />
              </svg>
              Consensus
            </span>
          </>
        ) : (
          <LegendDot color={NEUTRAL} label="Reported EPS" />
        )}
      </div>
    </div>
  );
}

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <svg width="10" height="10" aria-hidden="true">
        <circle cx="5" cy="5" r="4" fill={color} />
      </svg>
      {label}
    </span>
  );
}
