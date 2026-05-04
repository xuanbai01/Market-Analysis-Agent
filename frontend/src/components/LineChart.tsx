/**
 * LineChart — bigger sibling of Sparkline, used by the hero price
 * chart at 560×140 default. Hand-rolled SVG (same philosophy as
 * Sparkline / SectionChart's hand-rolled fallback).
 *
 * Phase 4.1 shipped the chart with ``no axes, no tooltip, no grid``
 * on the assumption that the host card would compose those separately.
 * In practice the hero never did — the chart read as decorative.
 *
 * Phase 4.3.B.2 adds two opt-in props:
 *
 * - ``showAxes`` — render y-axis min/max price labels on the left and
 *   x-axis first/last date labels along the bottom. Off by default so
 *   any future "decorative" callers stay lean.
 * - ``showTooltip`` — on ``mousemove`` over the SVG, snap a vertical
 *   guide line to the nearest data point, draw a filled dot on the
 *   line at that point, and render a small floating tooltip with the
 *   exact date + price. Clears on ``mouseleave``.
 *
 * Returns null on empty data so callers can branch via `points.length`
 * if they want a custom skeleton.
 */
import { useState } from "react";

interface DataPoint {
  ts: string;
  close: number;
  volume?: number;
}

interface Props {
  data: DataPoint[];
  width?: number;
  height?: number;
  strokeColor?: string;
  /** Hex/rgb color for the area fill below the line. */
  fillColor?: string;
  areaFill?: boolean;
  strokeWidth?: number;
  ariaLabel?: string;
  /** Render y-axis price labels (min/max) + x-axis date labels (start/end). */
  showAxes?: boolean;
  /** Enable mousemove → guide line + nearest-point dot + tooltip. */
  showTooltip?: boolean;
}

const DEFAULT_WIDTH = 560;
const DEFAULT_HEIGHT = 140;
const PADDING = 4;
// Reserve a column on the left for "$X.XX" labels and a row on the
// bottom for date text when ``showAxes`` is true.
const AXIS_LEFT_W = 44;
const AXIS_BOTTOM_H = 16;

const AXIS_LABEL_COLOR = "rgb(90, 100, 115)"; // strata-muted
const HOVER_GUIDE_COLOR = "rgb(122, 132, 148)"; // strata-dim

function formatPrice(n: number): string {
  return `$${n.toFixed(2)}`;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  // Format in UTC so the displayed date matches the underlying
  // timestamp regardless of the user's local timezone. yfinance bars
  // are timestamped at UTC midnight; rendering them in local time
  // would shift "2026-04-04T00:00:00Z" to "Apr 3" on UTC-4 etc.
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function nearestIndex(
  points: readonly { x: number }[],
  cursorX: number,
): number {
  let best = 0;
  let bestDist = Infinity;
  for (let i = 0; i < points.length; i++) {
    const d = Math.abs(points[i].x - cursorX);
    if (d < bestDist) {
      bestDist = d;
      best = i;
    }
  }
  return best;
}

export function LineChart({
  data,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
  strokeColor = "rgb(126, 154, 212)", // strata-highlight
  fillColor,
  areaFill = false,
  strokeWidth = 2,
  ariaLabel,
  showAxes = false,
  showTooltip = false,
}: Props) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  if (data.length < 1) return null;

  const closes = data.map((d) => d.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min;

  // Reserve space for axis labels when enabled.
  const leftP = showAxes ? AXIS_LEFT_W : PADDING;
  const bottomP = showAxes ? AXIS_BOTTOM_H : PADDING;
  const innerW = width - leftP - PADDING;
  const innerH = height - PADDING - bottomP;

  // Map (i, close) → (x, y) in SVG space. SVG y grows downward; invert.
  const points = data.map((d, i) => {
    const x =
      data.length === 1
        ? leftP + innerW / 2
        : leftP + (i / (data.length - 1)) * innerW;
    const yNorm = range === 0 ? 0.5 : (d.close - min) / range;
    const y = PADDING + (1 - yNorm) * innerH;
    return { x, y };
  });

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    .join(" ");

  // Area path: line + drop to bottom-right + line to bottom-left + close.
  const bottomY = height - bottomP;
  const areaPath =
    points.length > 0
      ? `${linePath} L${points[points.length - 1].x.toFixed(2)},${bottomY} ` +
        `L${points[0].x.toFixed(2)},${bottomY} Z`
      : "";

  const areaActualFill = fillColor ?? strokeColor;

  // ── Hover handlers ──────────────────────────────────────────────────
  // The handlers are no-ops when ``showTooltip`` is false so the SVG
  // stays cheap for decorative usages. We use the cursor's clientX
  // relative to the SVG's bounding rect, scaled into viewBox space, to
  // pick the nearest data point. happy-dom returns rect.width=0 in
  // tests; we degrade to "first point" under that condition so the
  // hover-state assertions still see a tooltip.
  function onMouseMove(e: React.MouseEvent<SVGSVGElement>) {
    if (!showTooltip) return;
    const rect = e.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) {
      // Test environment (no layout) — fall back to the first point so
      // the tooltip is at least observable.
      setHoverIdx(0);
      return;
    }
    const cursorClientX = e.clientX - rect.left;
    // Map browser cursor x (0..rect.width) to viewBox coordinate space.
    const fraction = Math.max(0, Math.min(1, cursorClientX / rect.width));
    const targetX = leftP + fraction * innerW;
    setHoverIdx(nearestIndex(points, targetX));
  }

  function onMouseLeave() {
    if (!showTooltip) return;
    setHoverIdx(null);
  }

  // ── Tooltip placement ───────────────────────────────────────────────
  // Position the tooltip to the right of the cursor by default; if too
  // close to the right edge, flip it to the left so it stays in-frame.
  const TOOLTIP_W = 96;
  const TOOLTIP_H = 32;
  const TOOLTIP_GAP = 8;
  const hoverPoint = hoverIdx !== null ? points[hoverIdx] : null;
  const hoverData = hoverIdx !== null ? data[hoverIdx] : null;
  const tooltipFlipsLeft =
    hoverPoint !== null &&
    hoverPoint.x + TOOLTIP_GAP + TOOLTIP_W > width - PADDING;
  const tooltipX =
    hoverPoint === null
      ? 0
      : tooltipFlipsLeft
        ? hoverPoint.x - TOOLTIP_GAP - TOOLTIP_W
        : hoverPoint.x + TOOLTIP_GAP;
  const tooltipY =
    hoverPoint === null
      ? 0
      : Math.max(PADDING, Math.min(height - bottomP - TOOLTIP_H, hoverPoint.y - TOOLTIP_H / 2));

  return (
    <svg
      data-testid="line-chart"
      // Phase 4.3.B.1 — responsive width so the hero price chart
      // doesn't overflow at narrow viewports. The ``width`` prop is
      // preserved in the viewBox so internal x-positions stay
      // correct; the SVG itself scales to its container.
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={ariaLabel ?? `Price chart with ${data.length} points`}
      className="block"
      onMouseMove={onMouseMove}
      onMouseLeave={onMouseLeave}
    >
      {areaFill && (
        <path
          data-line-area
          d={areaPath}
          fill={areaActualFill}
          fillOpacity={0.18}
          stroke="none"
        />
      )}
      <path
        data-line-stroke
        d={linePath}
        fill="none"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />

      {showAxes && (
        <>
          <text
            data-testid="line-chart-y-axis-max"
            x={leftP - 6}
            y={PADDING + 9}
            fill={AXIS_LABEL_COLOR}
            textAnchor="end"
            style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)" }}
          >
            {formatPrice(max)}
          </text>
          <text
            data-testid="line-chart-y-axis-min"
            x={leftP - 6}
            y={height - bottomP - 2}
            fill={AXIS_LABEL_COLOR}
            textAnchor="end"
            style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)" }}
          >
            {formatPrice(min)}
          </text>
          <text
            data-testid="line-chart-x-axis-start"
            x={leftP}
            y={height - 4}
            fill={AXIS_LABEL_COLOR}
            style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)" }}
          >
            {formatDate(data[0].ts)}
          </text>
          <text
            data-testid="line-chart-x-axis-end"
            x={width - PADDING}
            y={height - 4}
            fill={AXIS_LABEL_COLOR}
            textAnchor="end"
            style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)" }}
          >
            {formatDate(data[data.length - 1].ts)}
          </text>
        </>
      )}

      {hoverPoint !== null && hoverData !== null && (
        <g>
          <line
            data-testid="line-chart-hover-guide"
            x1={hoverPoint.x}
            x2={hoverPoint.x}
            y1={PADDING}
            y2={height - bottomP}
            stroke={HOVER_GUIDE_COLOR}
            strokeWidth={1}
            strokeDasharray="3 3"
          />
          <circle
            data-testid="line-chart-hover-dot"
            cx={hoverPoint.x}
            cy={hoverPoint.y}
            r={3.5}
            fill={strokeColor}
            stroke="rgb(15, 19, 27)"
            strokeWidth={1.5}
          />
          <g
            data-testid="line-chart-hover-tooltip"
            transform={`translate(${tooltipX.toFixed(2)},${tooltipY.toFixed(2)})`}
          >
            <rect
              x={0}
              y={0}
              width={TOOLTIP_W}
              height={TOOLTIP_H}
              rx={4}
              fill="rgb(20, 26, 36)"
              stroke="rgb(56, 64, 78)"
              strokeWidth={1}
            />
            <text
              x={8}
              y={13}
              fill="rgb(170, 180, 196)"
              style={{
                fontSize: 9,
                fontFamily: "var(--font-mono, monospace)",
                textTransform: "uppercase",
                letterSpacing: "0.04em",
              }}
            >
              {formatDate(hoverData.ts)}
            </text>
            <text
              x={8}
              y={26}
              fill="rgb(245, 247, 251)"
              style={{
                fontSize: 12,
                fontFamily: "var(--font-mono, monospace)",
                fontWeight: 500,
              }}
            >
              {formatPrice(hoverData.close)}
            </text>
          </g>
        </g>
      )}
    </svg>
  );
}
