/**
 * MultiLine — 1–5 series on a shared period axis. Hand-rolled SVG.
 * Phase 4.2; rebuilt 2026-11 after the owner's dogfood review: "no
 * baseline, no process shown — I can't read it" (tasks/dogfood-2026-11.md
 * #8). Every chart now answers "what value, when, compared with what":
 *
 *   - Value axis: 3–6 clean ticks ("nice" steps of 1 / 2 / 2.5 / 5 × 10^k)
 *     labelled with the caller's ``formatValue``; solid hairline grid.
 *   - Baseline: a stronger solid line at zero whenever the scale reaches it
 *     (``includeZero`` forces that), or at ``baseline`` for indexed charts.
 *   - Period axis: every period labelled up to 8; longer histories keep
 *     both ends plus ~3 evenly spaced labels between them.
 *   - Lines: straight segments between the real points — the previous
 *     Catmull-Rom smoothing invented shapes between quarters.
 *   - Markers: every point on histories up to 12 periods, otherwise the
 *     latest point only.
 *   - End labels: each line's latest value at its right end, nudged apart
 *     so lines that finish together stay legible.
 *   - Hover: a guide at the nearest period and a readout listing every
 *     series at that period (plus ``formatChange`` vs the prior period).
 *   - ``yDomain`` lets sibling charts share one scale. A point outside
 *     it breaks the line and is marked by a triangle at the plot edge
 *     (2026-11: a line to an off-scale point ran out of the chart).
 *   - Drawn at the container's measured pixel width, so labels stay a
 *     true 11 px in any card instead of shrinking with a fixed viewBox
 *     (``width`` is the fallback before measurement and in tests).
 *
 * Period axis: the sorted union of every series' periods (lexical sort
 * works for ``YYYY-Qn`` / ``YYYY-MM`` / ``YYYY``). Series with < 2 points
 * are dropped.
 */
import { useCallback, useRef, useState } from "react";

import { shortPeriod } from "../lib/chart-format";
import type { ClaimHistoryPoint } from "../lib/schemas";

export interface MultiLineSeries {
  label: string;
  /** Short name for the end-of-line label, e.g. "Rev" for "Revenue". */
  shortLabel?: string;
  /** Hex/rgb color for the series stroke and markers. */
  color: string;
  history: ClaimHistoryPoint[];
}

interface Props {
  series: MultiLineSeries[];
  width?: number;
  height?: number;
  /** Whether to render the legend chip row below the chart. */
  showLegend?: boolean;
  /** Label each line's latest value at its right end. */
  showEndLabels?: boolean;
  /** Formats end labels and the hover readout (and ticks, unless formatTick). */
  formatValue?: (v: number) => string;
  /** Formats value-axis ticks; defaults to formatValue. */
  formatTick?: (v: number) => string;
  /** Hover readout suffix comparing a period with the one before it. */
  formatChange?: (now: number, prev: number) => string;
  /** Extend the scale to include zero (and draw the zero baseline). */
  includeZero?: boolean;
  /** Fixed raw [min, max] so sibling charts share one scale. A point
   *  outside the resulting scale is not drawn to: the line breaks there
   *  and a small triangle at the plot's edge marks the period. */
  yDomain?: [number, number];
  /** Emphasized reference line, e.g. 100 for an indexed chart. */
  baseline?: number;
  /** Formats period labels and the hover header; defaults to "Q3 '25". */
  formatPeriod?: (period: string) => string;
  /** Every slot on the period axis, in order. Without it the axis is
   *  the periods that have a point, so a skipped year closes up and the
   *  line joins its neighbours; with it, a slot with no point stays on
   *  the axis and the line breaks across it. */
  periodAxis?: string[];
  ariaLabel?: string;
}

const DEFAULT_WIDTH = 560;
const DEFAULT_HEIGHT = 180;
const MAX_ALL_X_LABELS = 8;
const THINNED_X_LABELS = 5;
const MAX_MARKED_PERIODS = 12;
const END_LABEL_GAP = 13;
const CHAR_W = 6.7; // ~11 px mono glyph width in viewBox units
const PAD_TOP = 10;
const PAD_BOTTOM = 22;

const GRID_COLOR = "#1f2630"; // strata-line
const BASELINE_COLOR = "#5a6473"; // strata-muted
const AXIS_LABEL_COLOR = "#5a6473"; // strata-muted
const END_LABEL_COLOR = "#8892a0"; // strata-dim
const MARKER_RING = "#0e1116"; // strata-surface
const LABEL_STYLE = { fontSize: 11, fontFamily: "var(--font-mono, monospace)" };

function defaultFormat(v: number): string {
  const abs = Math.abs(v);
  if (abs >= 1e12) return `${(v / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  return String(Number(v.toFixed(2)));
}

function niceStep(raw: number): number {
  const exp = Math.floor(Math.log10(raw));
  const base = 10 ** exp;
  const f = raw / base;
  const nice = f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10;
  return nice * base;
}

/** Clean ticks covering [min, max]; the first/last tick bound the scale. */
export function niceTicks(min: number, max: number, target = 4): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) {
    const pad = Math.abs(min) * 0.1 || 1;
    min -= pad;
    max += pad;
  }
  const step = niceStep((max - min) / target);
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks: number[] = [];
  for (let v = lo; v <= hi + step / 2; v += step) {
    const clean = Number(v.toFixed(10));
    ticks.push(clean === 0 ? 0 : clean); // no "-0"
  }
  return ticks;
}

function evenlySpaced(n: number, k: number): number[] {
  if (k >= n) return Array.from({ length: n }, (_, i) => i);
  const picks = new Set<number>();
  for (let i = 0; i < k; i++) picks.add(Math.round((i * (n - 1)) / (k - 1)));
  return Array.from(picks).sort((a, b) => a - b);
}

/** Which period indices get a label: as many as fit without touching —
 *  every period up to 8, otherwise at most 5 — always keeping both ends.
 *  The first label is anchored at its start and the last at its end, so
 *  extents are checked per anchor rather than assuming equal spacing. */
function pickXTicks(n: number, xAt: (i: number) => number, labelPx: number): number[] {
  const kMax = n <= MAX_ALL_X_LABELS ? n : THINNED_X_LABELS;
  for (let k = kMax; k >= 2; k--) {
    const idx = evenlySpaced(n, k);
    const extents = idx.map((i, j) => {
      const x = xAt(i);
      if (j === 0) return [x, x + labelPx];
      if (j === idx.length - 1) return [x - labelPx, x];
      return [x - labelPx / 2, x + labelPx / 2];
    });
    if (extents.every((e, j) => j === 0 || e[0] >= extents[j - 1][1] + 4)) return idx;
  }
  return n > 1 ? [0, n - 1] : [0];
}

function sortedHistory(h: ClaimHistoryPoint[]): ClaimHistoryPoint[] {
  return [...h].sort((a, b) => (a.period < b.period ? -1 : a.period > b.period ? 1 : 0));
}

export function MultiLine({
  series,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
  showLegend = true,
  showEndLabels = true,
  formatValue = defaultFormat,
  formatTick,
  formatChange,
  includeZero = false,
  yDomain,
  baseline,
  formatPeriod = shortPeriod,
  periodAxis,
  ariaLabel,
}: Props) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [measuredWidth, setMeasuredWidth] = useState<number | null>(null);
  const observer = useRef<ResizeObserver | null>(null);
  const measureRef = useCallback((el: HTMLDivElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect.width ?? 0);
      if (w > 0) setMeasuredWidth((prev) => (prev === w ? prev : w));
    });
    ro.observe(el);
    observer.current = ro;
  }, []);

  const drawable = series
    .filter((s) => s.history.length >= 2)
    .map((s) => ({ ...s, history: sortedHistory(s.history) }));
  if (drawable.length === 0) return null;

  const periods =
    periodAxis ??
    Array.from(new Set(drawable.flatMap((s) => s.history.map((p) => p.period)))).sort();
  const periodIndex = new Map(periods.map((p, i) => [p, i]));

  // ── Scale ──────────────────────────────────────────────────────────
  const values = drawable.flatMap((s) => s.history.map((p) => p.value));
  let rawMin = yDomain ? yDomain[0] : Math.min(...values);
  let rawMax = yDomain ? yDomain[1] : Math.max(...values);
  if (includeZero) {
    rawMin = Math.min(rawMin, 0);
    rawMax = Math.max(rawMax, 0);
  }
  if (baseline !== undefined) {
    rawMin = Math.min(rawMin, baseline);
    rawMax = Math.max(rawMax, baseline);
  }
  const ticks = niceTicks(rawMin, rawMax);
  const yLo = ticks[0];
  const yHi = ticks[ticks.length - 1];
  const referenceValue = baseline ?? (yLo <= 0 && yHi >= 0 ? 0 : undefined);

  // ── Layout (viewBox units = CSS px once measured) ──────────────────
  const W = measuredWidth ?? width;
  const tickLabels = ticks.map(formatTick ?? formatValue);
  const padLeft = 10 + Math.max(...tickLabels.map((t) => t.length)) * CHAR_W;
  const endTexts = drawable.map((s) => {
    const last = s.history[s.history.length - 1];
    return `${s.shortLabel ?? s.label} ${formatValue(last.value)}`;
  });
  const padRight = showEndLabels
    ? Math.min(130, 14 + Math.max(...endTexts.map((t) => t.length)) * CHAR_W)
    : 12;
  const innerW = W - padLeft - padRight;
  const innerH = height - PAD_TOP - PAD_BOTTOM;
  const plotRight = padLeft + innerW;
  const plotBottom = PAD_TOP + innerH;

  const xAt = (i: number) =>
    padLeft + (periods.length === 1 ? innerW / 2 : (i / (periods.length - 1)) * innerW);
  const xOf = (period: string) => xAt(periodIndex.get(period) ?? 0);
  const yOf = (v: number) => PAD_TOP + (1 - (v - yLo) / (yHi - yLo || 1)) * innerH;

  // ── End labels, nudged apart top-to-bottom ─────────────────────────
  const endLabels = drawable
    .map((s, i) => ({
      key: s.label,
      text: endTexts[i],
      y: Math.max(PAD_TOP, Math.min(plotBottom, yOf(s.history[s.history.length - 1].value))),
    }))
    .sort((a, b) => a.y - b.y);
  for (let i = 1; i < endLabels.length; i++) {
    endLabels[i].y = Math.max(endLabels[i].y, endLabels[i - 1].y + END_LABEL_GAP);
  }
  const overflow = endLabels.length ? endLabels[endLabels.length - 1].y - plotBottom : 0;
  if (overflow > 0) for (const l of endLabels) l.y -= overflow;

  const markAll = periods.length <= MAX_MARKED_PERIODS;

  const xLabelPx = Math.max(...periods.map((p) => formatPeriod(p).length)) * CHAR_W;
  const xTicks = pickXTicks(periods.length, xAt, xLabelPx);

  // ── Hover ──────────────────────────────────────────────────────────
  function onMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) {
      // No layout (tests): show the latest period.
      setHoverIdx(periods.length - 1);
      return;
    }
    const vbX = ((e.clientX - rect.left) / rect.width) * W;
    const frac = (vbX - padLeft) / (innerW || 1);
    setHoverIdx(Math.max(0, Math.min(periods.length - 1, Math.round(frac * (periods.length - 1)))));
  }

  const hoverPeriod = hoverIdx === null ? null : periods[hoverIdx];
  const hoverRows =
    hoverPeriod === null
      ? []
      : drawable.flatMap((s) => {
          const i = s.history.findIndex((p) => p.period === hoverPeriod);
          if (i < 0) return [];
          const now = s.history[i].value;
          const prev = i > 0 ? s.history[i - 1].value : null;
          const change = formatChange && prev !== null ? formatChange(now, prev) : null;
          return [{ s, now, change }];
        });
  const hoverLeftPct = hoverIdx === null ? 0 : (xAt(hoverIdx) / W) * 100;

  return (
    <div>
      <div className="relative" ref={measureRef}>
        <svg
          data-testid="multi-line"
          // Responsive width; internal coords preserved by the viewBox.
          width="100%"
          height={height}
          viewBox={`0 0 ${W} ${height}`}
          role="img"
          aria-label={ariaLabel ?? `Multi-series chart with ${drawable.length} series`}
          className="block"
          onMouseMove={onMouseMove}
          onMouseLeave={() => setHoverIdx(null)}
        >
          {/* Value axis: grid + tick labels. */}
          {ticks.map((t, i) => (
            <g key={t}>
              {t !== referenceValue && (
                <line x1={padLeft} x2={plotRight} y1={yOf(t)} y2={yOf(t)} stroke={GRID_COLOR} strokeWidth={1} />
              )}
              <text
                data-testid="multi-line-y-tick"
                x={padLeft - 6}
                y={yOf(t) + 3.5}
                textAnchor="end"
                fill={AXIS_LABEL_COLOR}
                style={LABEL_STYLE}
              >
                {tickLabels[i]}
              </text>
            </g>
          ))}
          {referenceValue !== undefined && (
            <line
              data-testid="multi-line-baseline"
              x1={padLeft}
              x2={plotRight}
              y1={yOf(referenceValue)}
              y2={yOf(referenceValue)}
              stroke={BASELINE_COLOR}
              strokeWidth={1}
            />
          )}

          {/* Period axis labels. */}
          {xTicks.map((i, k, all) => (
            <text
              key={periods[i]}
              data-testid="multi-line-x-tick"
              data-period={periods[i]}
              x={xAt(i)}
              y={height - 6}
              textAnchor={k === 0 ? "start" : k === all.length - 1 ? "end" : "middle"}
              fill={AXIS_LABEL_COLOR}
              style={LABEL_STYLE}
            >
              {formatPeriod(periods[i])}
            </text>
          ))}

          {hoverIdx !== null && (
            <line
              data-testid="multi-line-hover-guide"
              x1={xAt(hoverIdx)}
              x2={xAt(hoverIdx)}
              y1={PAD_TOP}
              y2={plotBottom}
              stroke={BASELINE_COLOR}
              strokeWidth={1}
            />
          )}

          {/* Lines + markers. */}
          {drawable.map((s) => {
            const all = s.history
              .filter((p) => periodIndex.has(p.period))
              .map((p) => ({
              slot: periodIndex.get(p.period) ?? 0,
              x: xOf(p.period),
              y: yOf(p.value),
              // Only a fixed yDomain can leave a point outside the ticks.
              off: p.value > yHi ? ("above" as const) : p.value < yLo ? ("below" as const) : null,
            }));
            // With an explicit axis, a skipped slot is missing data.
            const starts = (i: number) =>
              i === 0 ||
              all[i - 1].off !== null ||
              (periodAxis !== undefined && all[i].slot !== all[i - 1].slot + 1);
            const pts = all.filter((p) => p.off === null);
            // The line restarts after a point it can't reach, so it never
            // leaves the plot or implies a slope to an undrawn value.
            const d = all
              .map((p, i) =>
                p.off !== null ? "" : `${starts(i) ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`,
              )
              .filter(Boolean)
              .join(" ");
            const marked = markAll ? pts : pts.slice(-1);
            return (
              <g key={s.label}>
                <path
                  data-series-line={s.label}
                  d={d}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
                {all
                  .filter((p) => p.off !== null)
                  .map((p, i) => {
                    const up = p.off === "above";
                    const tip = up ? PAD_TOP - 2 : plotBottom + 2;
                    const base = up ? PAD_TOP + 6 : plotBottom - 6;
                    return (
                      <path
                        key={`off-${i}`}
                        data-testid="multi-line-off-scale"
                        data-direction={p.off ?? undefined}
                        d={`M${p.x.toFixed(2)},${tip} L${(p.x + 5).toFixed(2)},${base} L${(p.x - 5).toFixed(2)},${base} Z`}
                        fill={s.color}
                        stroke={MARKER_RING}
                        strokeWidth={1}
                      />
                    );
                  })}
                {marked.map((p, i) => (
                  <circle
                    key={i}
                    data-testid="multi-line-marker"
                    cx={p.x}
                    cy={p.y}
                    r={3.5}
                    fill={s.color}
                    stroke={MARKER_RING}
                    strokeWidth={2}
                  />
                ))}
              </g>
            );
          })}

          {showEndLabels &&
            endLabels.map((l) => (
              <text
                key={l.key}
                data-testid="multi-line-end-label"
                x={plotRight + 8}
                y={l.y + 3.5}
                fill={END_LABEL_COLOR}
                style={LABEL_STYLE}
              >
                {l.text}
              </text>
            ))}
        </svg>

        {hoverPeriod !== null && hoverRows.length > 0 && (
          <div
            data-testid="multi-line-tooltip"
            className="pointer-events-none absolute top-0 z-10 rounded-md border border-strata-border bg-strata-raise px-2.5 py-1.5 font-mono text-[10px] text-strata-fg shadow-sm"
            style={{
              left: `${hoverLeftPct}%`,
              transform: hoverLeftPct > 55 ? "translateX(calc(-100% - 8px))" : "translateX(8px)",
            }}
          >
            <div className="mb-1 text-strata-dim">{formatPeriod(hoverPeriod)}</div>
            {hoverRows.map(({ s, now, change }) => (
              <div key={s.label} className="flex items-center gap-1.5 whitespace-nowrap">
                <span aria-hidden="true" className="inline-block h-1.5 w-1.5 rounded-sm" style={{ backgroundColor: s.color }} />
                <span className="text-strata-dim">{s.label}</span>
                <span className="tabular text-strata-hi">{formatValue(now)}</span>
                {change && <span className="text-strata-muted">{change}</span>}
              </div>
            ))}
          </div>
        )}
      </div>

      {showLegend && (
        <div className="mt-2 flex flex-wrap gap-3">
          {drawable.map((s) => (
            <div
              key={s.label}
              className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-kicker text-strata-dim"
            >
              <span aria-hidden="true" className="inline-block h-1.5 w-3 rounded-sm" style={{ backgroundColor: s.color }} />
              {s.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
