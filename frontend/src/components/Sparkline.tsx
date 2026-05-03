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
 * For the inline case we hand-roll an SVG path: tiny, ~30 lines, no
 * external dep cost in the bundle, no test-environment rendering
 * pitfalls. The bigger ``SectionChart`` (Phase 3.3.B) will use the
 * full Recharts toolkit where the per-section card has explicit
 * width.
 *
 * ## Visual contract
 *
 * - default 80×24 px (table-cell-friendly)
 * - 1.5 px stroke, slate-700 (matches the report's slate palette)
 * - small dot on the most-recent point (subtle "you are here" anchor)
 * - no axes, no grid, no tooltip, no legend
 * - returns null when history.length < 2 (a single point isn't a trend)
 */
import type { ClaimHistoryPoint } from "../lib/schemas";

interface Props {
  history: ClaimHistoryPoint[];
  width?: number;
  height?: number;
  ariaLabel?: string;
}

const DEFAULT_WIDTH = 80;
const DEFAULT_HEIGHT = 24;
// Inset so the stroke + endpoint dot don't clip the SVG box.
const PADDING = 2;

export function Sparkline({
  history,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
  ariaLabel,
}: Props) {
  if (history.length < 2) return null;

  const values = history.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min;

  const innerW = width - PADDING * 2;
  const innerH = height - PADDING * 2;

  // Map each (i, value) point to (x, y) in SVG space. Note: SVG y grows
  // downward; we invert so larger values are higher on the chart.
  const points = history.map((p, i) => {
    const x = PADDING + (i / (history.length - 1)) * innerW;
    // Flat line (range == 0) → mid-height; otherwise normalize.
    const yNorm = range === 0 ? 0.5 : (p.value - min) / range;
    const y = PADDING + (1 - yNorm) * innerH;
    return { x, y };
  });

  const pathD = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    .join(" ");

  const last = points[points.length - 1];
  const defaultLabel = `Trend with ${history.length} points`;

  return (
    <svg
      data-testid="sparkline"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={ariaLabel ?? defaultLabel}
      className="inline-block align-middle"
    >
      <path
        d={pathD}
        fill="none"
        stroke="rgb(122, 208, 166)" /* strata-quality — neutral on dark, gets per-claim color in 4.2+ */
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={last.x}
        cy={last.y}
        r={1.75}
        fill="rgb(122, 208, 166)" /* strata-quality */
      />
    </svg>
  );
}
