/**
 * LineChart — bigger sibling of Sparkline, used by the hero price
 * chart at 560×140 default. Hand-rolled SVG (same philosophy as
 * Sparkline / SectionChart's hand-rolled fallback).
 *
 * Phase 4.1.
 *
 * Renders a closing-price line (slate-700 stroke by default), with an
 * optional area fill below the line. No axes, no tooltip, no grid —
 * the hero card composes those separately around the chart.
 *
 * Returns null on empty data so callers can branch via `points.length`
 * if they want a custom skeleton.
 */
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
}

const DEFAULT_WIDTH = 560;
const DEFAULT_HEIGHT = 140;
const PADDING = 4;

export function LineChart({
  data,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
  strokeColor = "rgb(126, 154, 212)", // strata-highlight
  fillColor,
  areaFill = false,
  strokeWidth = 2,
  ariaLabel,
}: Props) {
  if (data.length < 1) return null;

  const closes = data.map((d) => d.close);
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min;

  const innerW = width - PADDING * 2;
  const innerH = height - PADDING * 2;

  // Map (i, close) → (x, y) in SVG space. SVG y grows downward; invert.
  const points = data.map((d, i) => {
    const x =
      data.length === 1
        ? PADDING + innerW / 2
        : PADDING + (i / (data.length - 1)) * innerW;
    const yNorm = range === 0 ? 0.5 : (d.close - min) / range;
    const y = PADDING + (1 - yNorm) * innerH;
    return { x, y };
  });

  const linePath = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(2)},${p.y.toFixed(2)}`)
    .join(" ");

  // Area path: line + drop to bottom-right + line to bottom-left + close.
  const bottomY = height - PADDING;
  const areaPath =
    points.length > 0
      ? `${linePath} L${points[points.length - 1].x.toFixed(2)},${bottomY} ` +
        `L${points[0].x.toFixed(2)},${bottomY} Z`
      : "";

  const areaActualFill = fillColor ?? strokeColor;

  return (
    <svg
      data-testid="line-chart"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={ariaLabel ?? `Price chart with ${data.length} points`}
      className="block"
    >
      {areaFill && (
        <path
          d={areaPath}
          fill={areaActualFill}
          fillOpacity={0.18}
          stroke="none"
        />
      )}
      <path
        d={linePath}
        fill="none"
        stroke={strokeColor}
        strokeWidth={strokeWidth}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
