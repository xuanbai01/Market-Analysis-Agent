/**
 * Sparkline — a tiny inline chart for a Claim's history.
 *
 * ## Why a custom SVG, not Recharts ResponsiveContainer
 *
 * The inline-table use case wants explicit, fixed pixel dimensions
 * (one cell per row, identical width). Recharts' ResponsiveContainer
 * relies on ``getBoundingClientRect()`` which returns 0 in happy-dom
 * tests and triggers a "container not measured" silent fail in
 * real browsers when nested in a table-cell with ``display: table-cell``.
 *
 * ## Visual contract
 *
 * - default 80×24 px (table-cell-friendly); ``width="100%"`` fills a tile
 *   while keeping the drawing's proportions
 * - 1.5 px stroke in ``color`` (default strata-quality)
 * - hollow dot on the first point, filled dot on the latest (2026-11:
 *   both ends marked so a reader sees where the line starts and finishes)
 * - no axes, no grid, no tooltip, no legend — callers state the change in
 *   text next to it (TrendCell, the Cash & capital tiles)
 * - returns null when history.length < 2 (a single point isn't a trend)
 */
import type { ClaimHistoryPoint } from "../lib/schemas";

interface Props {
  history: ClaimHistoryPoint[];
  width?: number | string;
  height?: number;
  color?: string;
  ariaLabel?: string;
}

const DEFAULT_WIDTH = 80;
const DEFAULT_HEIGHT = 24;
// Drawing width used when the rendered width is fluid ("100%").
const FLUID_VIEWBOX_WIDTH = 120;
const DEFAULT_COLOR = "rgb(122, 208, 166)"; // strata-quality
const SURFACE = "#0e1116"; // strata-surface, fills the hollow start dot
// Inset so the stroke + end dots don't clip the SVG box.
const PADDING = 3.5;

export function Sparkline({
  history,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
  color = DEFAULT_COLOR,
  ariaLabel,
}: Props) {
  if (history.length < 2) return null;

  const vbWidth = typeof width === "number" ? width : FLUID_VIEWBOX_WIDTH;
  const values = history.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min;

  const innerW = vbWidth - PADDING * 2;
  const innerH = height - PADDING * 2;

  // SVG y grows downward; invert so larger values sit higher.
  const points = history.map((p, i) => {
    const x = PADDING + (i / (history.length - 1)) * innerW;
    const yNorm = range === 0 ? 0.5 : (p.value - min) / range;
    const y = PADDING + (1 - yNorm) * innerH;
    return { x, y };
  });

  const pathD = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    .join(" ");

  const first = points[0];
  const last = points[points.length - 1];

  return (
    <svg
      data-testid="sparkline"
      width={width}
      height={height}
      viewBox={`0 0 ${vbWidth} ${height}`}
      preserveAspectRatio="xMinYMid meet"
      role="img"
      aria-label={ariaLabel ?? `Trend with ${history.length} points`}
      className="inline-block align-middle"
    >
      <path
        d={pathD}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle data-testid="sparkline-start" cx={first.x} cy={first.y} r={2} fill={SURFACE} stroke={color} strokeWidth={1.25} />
      <circle data-testid="sparkline-end" cx={last.x} cy={last.y} r={2.5} fill={color} />
    </svg>
  );
}
