/**
 * MultiLine — 2-4 series on a shared period axis. Hand-rolled SVG.
 * Phase 4.2.
 *
 * Used by QualityCard to render gross / operating / FCF margin together
 * on one chart. Replaces the multi-series-on-one-axis use case that
 * SectionChart's ``primary + secondary`` pattern only half-served (only
 * 2 series, only one is "primary"). MultiLine is the symmetric N-series
 * primitive.
 *
 * Layout:
 *   - X axis: period strings, evenly spaced. First and last labels
 *     render as ticks below the chart; intermediate periods just get
 *     a vertical grid line.
 *   - Y axis: auto-detected min/max across all series with 5% padding.
 *     Three faint horizontal grid lines (min, mid, max).
 *   - Series: one ``<path>`` per series with the series' accent color.
 *   - Legend: a row of color-swatch + label chips below the chart.
 *
 * Period axis strategy: each series may have a different period set
 * (some quarters missing data). We collect the union of periods,
 * sort them lexically (works for ``YYYY-Qn`` / ``YYYY-MM`` / ``YYYY``),
 * and plot each series at the X position of its periods. Series with
 * < 2 valid points are dropped (nothing to draw).
 */
import type { ClaimHistoryPoint } from "../lib/schemas";

export interface MultiLineSeries {
  label: string;
  /** Hex/rgb color for the series stroke. */
  color: string;
  history: ClaimHistoryPoint[];
}

interface Props {
  series: MultiLineSeries[];
  width?: number;
  height?: number;
  /** Whether to render the legend chip row below the chart. */
  showLegend?: boolean;
  ariaLabel?: string;
}

const DEFAULT_WIDTH = 560;
const DEFAULT_HEIGHT = 180;

/** Build a smooth SVG path through ``points`` using Catmull-Rom-to-Bezier
 *  cubic interpolation. Uses tension 1/6 (the standard CR derivative);
 *  endpoint control points mirror the nearest neighbor so the curve
 *  starts/ends tangent to its data without spurious oscillation. */
function smoothPath(points: { x: number; y: number }[]): string {
  if (points.length === 0) return "";
  const fmt = (n: number) => n.toFixed(2);
  if (points.length === 1) return `M${fmt(points[0].x)},${fmt(points[0].y)}`;
  let d = `M${fmt(points[0].x)},${fmt(points[0].y)}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[Math.max(0, i - 1)];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[Math.min(points.length - 1, i + 2)];
    const c1x = p1.x + (p2.x - p0.x) / 6;
    const c1y = p1.y + (p2.y - p0.y) / 6;
    const c2x = p2.x - (p3.x - p1.x) / 6;
    const c2y = p2.y - (p3.y - p1.y) / 6;
    d += ` C${fmt(c1x)},${fmt(c1y)} ${fmt(c2x)},${fmt(c2y)} ${fmt(p2.x)},${fmt(p2.y)}`;
  }
  return d;
}
const PADDING_TOP = 8;
const PADDING_BOTTOM = 24; // room for X-axis label
const PADDING_LEFT = 8;
const PADDING_RIGHT = 8;
const GRID_COLOR = "rgb(31, 38, 48)"; // strata-line
const AXIS_LABEL_COLOR = "rgb(90, 100, 115)"; // strata-muted

export function MultiLine({
  series,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
  showLegend = true,
  ariaLabel,
}: Props) {
  if (series.length === 0) return null;

  // Drop series with < 2 points; they have nothing to draw.
  const drawable = series.filter((s) => s.history.length >= 2);
  if (drawable.length === 0) return null;

  // Build a canonical period axis as the sorted union of every series's
  // periods. Sort lexically — works for the cadences our backend emits.
  const periodSet = new Set<string>();
  for (const s of drawable) {
    for (const p of s.history) periodSet.add(p.period);
  }
  const periods = Array.from(periodSet).sort();
  const periodIndex = new Map<string, number>();
  periods.forEach((p, i) => periodIndex.set(p, i));

  // Y range across every drawable series.
  const allValues: number[] = [];
  for (const s of drawable) {
    for (const p of s.history) allValues.push(p.value);
  }
  const rawMin = Math.min(...allValues);
  const rawMax = Math.max(...allValues);
  const span = rawMax - rawMin || 1;
  const yMin = rawMin - span * 0.05;
  const yMax = rawMax + span * 0.05;
  const yRange = yMax - yMin || 1;

  const innerW = width - PADDING_LEFT - PADDING_RIGHT;
  const innerH = height - PADDING_TOP - PADDING_BOTTOM;

  function xOf(period: string): number {
    const i = periodIndex.get(period) ?? 0;
    if (periods.length === 1) {
      return PADDING_LEFT + innerW / 2;
    }
    return PADDING_LEFT + (i / (periods.length - 1)) * innerW;
  }
  function yOf(value: number): number {
    return PADDING_TOP + (1 - (value - yMin) / yRange) * innerH;
  }

  const firstPeriod = periods[0];
  const lastPeriod = periods[periods.length - 1];
  const midY = PADDING_TOP + innerH / 2;
  const bottomY = PADDING_TOP + innerH;

  return (
    <div>
      <svg
        data-testid="multi-line"
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={
          ariaLabel ?? `Multi-series chart with ${drawable.length} series`
        }
        className="block"
      >
        {/* Horizontal grid lines: top, middle, bottom. */}
        <line
          x1={PADDING_LEFT}
          x2={width - PADDING_RIGHT}
          y1={PADDING_TOP}
          y2={PADDING_TOP}
          stroke={GRID_COLOR}
          strokeWidth={1}
        />
        <line
          x1={PADDING_LEFT}
          x2={width - PADDING_RIGHT}
          y1={midY}
          y2={midY}
          stroke={GRID_COLOR}
          strokeWidth={1}
          strokeDasharray="2 4"
        />
        <line
          x1={PADDING_LEFT}
          x2={width - PADDING_RIGHT}
          y1={bottomY}
          y2={bottomY}
          stroke={GRID_COLOR}
          strokeWidth={1}
        />

        {/* Series paths. Phase 4.3.X — monotone cubic Bézier curves
            (Catmull-Rom-to-Bezier) instead of straight L-segments to
            match the design's smooth-curve treatment. The control
            points use a tension of 1/6 so the curve hugs the data
            points without overshoot on flat segments. */}
        {drawable.map((s) => {
          const sortedPoints = [...s.history].sort((a, b) =>
            a.period < b.period ? -1 : a.period > b.period ? 1 : 0,
          );
          const xy = sortedPoints.map((p) => ({
            x: xOf(p.period),
            y: yOf(p.value),
          }));
          return (
            <path
              key={s.label}
              data-series-line={s.label}
              d={smoothPath(xy)}
              fill="none"
              stroke={s.color}
              strokeWidth={1.8}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          );
        })}

        {/* X-axis labels: first + last period only. */}
        <text
          x={PADDING_LEFT}
          y={height - 6}
          fill={AXIS_LABEL_COLOR}
          style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)" }}
        >
          {firstPeriod}
        </text>
        <text
          x={width - PADDING_RIGHT}
          y={height - 6}
          fill={AXIS_LABEL_COLOR}
          textAnchor="end"
          style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)" }}
        >
          {lastPeriod}
        </text>
      </svg>
      {showLegend && (
        <div className="mt-2 flex flex-wrap gap-3">
          {drawable.map((s) => (
            <div
              key={s.label}
              className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-kicker text-strata-dim"
            >
              <span
                aria-hidden="true"
                className="inline-block h-1.5 w-3 rounded-sm"
                style={{ backgroundColor: s.color }}
              />
              {s.label}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
