/**
 * EpsBars — 20-bar quarterly EPS chart for the EarningsCard. Phase 4.1.
 *
 * Each bar is one quarter's actual EPS. Color encodes beat (>= estimate
 * ⇒ pos color) vs miss (< estimate ⇒ neg color). When an estimate
 * exists for the same period, a small horizontal tick renders at the
 * estimate value across the top of the bar — visual delta between
 * actual and consensus.
 *
 * Hand-rolled SVG. Returns null on empty actuals.
 */
import type { ClaimHistoryPoint } from "../lib/schemas";

interface Props {
  actual: ClaimHistoryPoint[];
  estimate: ClaimHistoryPoint[];
  width?: number;
  height?: number;
  posColor?: string;
  negColor?: string;
  estColor?: string;
}

const DEFAULT_WIDTH = 560;
const DEFAULT_HEIGHT = 150;
const PADDING_TOP = 6;
const PADDING_BOTTOM = 6;
const PADDING_X = 4;
const BAR_GAP = 3;

export function EpsBars({
  actual,
  estimate,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
  posColor = "rgb(95, 191, 138)", // strata-pos
  negColor = "rgb(229, 124, 110)", // strata-neg
  estColor = "rgb(90, 100, 115)", // strata-muted
}: Props) {
  if (actual.length === 0) return null;

  // Build a period → estimate value lookup so we can co-render ticks
  // for the periods that have a matching estimate.
  const estByPeriod = new Map<string, number>();
  for (const e of estimate) estByPeriod.set(e.period, e.value);

  const innerW = width - PADDING_X * 2;
  const innerH = height - PADDING_TOP - PADDING_BOTTOM;
  const slot = innerW / actual.length;
  const barW = Math.max(1, slot - BAR_GAP);

  // Y-scale spans the union of actuals + matching estimates so the
  // estimate ticks always sit inside the bar's vertical range.
  const allValues: number[] = [...actual.map((a) => a.value)];
  for (const a of actual) {
    const est = estByPeriod.get(a.period);
    if (est !== undefined) allValues.push(est);
  }
  const minVal = Math.min(0, ...allValues);
  const maxVal = Math.max(0, ...allValues);
  const valRange = maxVal - minVal || 1;

  // Y for a value, in SVG space (top = 0 = high value, bottom = max y).
  function yOf(v: number): number {
    const norm = (v - minVal) / valRange;
    return PADDING_TOP + (1 - norm) * innerH;
  }

  // Zero baseline — bars grow from the zero line up (positive) or
  // down (negative). For all-positive series, baseline = bottom.
  const yZero = yOf(0);

  return (
    <svg
      data-testid="eps-bars"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`EPS bars with ${actual.length} quarters`}
      className="block"
    >
      {actual.map((a, i) => {
        const x = PADDING_X + i * slot + BAR_GAP / 2;
        const yVal = yOf(a.value);
        const barTop = Math.min(yVal, yZero);
        const barH = Math.abs(yVal - yZero);

        const est = estByPeriod.get(a.period);
        const beat = est !== undefined ? a.value >= est : true;
        const fill = beat ? posColor : negColor;

        return (
          <g key={`${a.period}-${i}`}>
            <rect
              data-bar="actual"
              data-period={a.period}
              x={x}
              y={barTop}
              width={barW}
              height={Math.max(1, barH)}
              fill={fill}
              rx={1}
            />
            {est !== undefined && (
              <line
                data-tick="estimate"
                data-period={a.period}
                x1={x - 1}
                x2={x + barW + 1}
                y1={yOf(est)}
                y2={yOf(est)}
                stroke={estColor}
                strokeWidth={1.5}
              />
            )}
          </g>
        );
      })}
    </svg>
  );
}
