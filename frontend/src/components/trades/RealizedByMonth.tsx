/**
 * RealizedByMonth — the journal's realized P&L by the month positions
 * closed: one bar a month from a single zero line, gains up in the pos
 * token, losses down in the neg one (polarity, not a series: no legend;
 * the panel title names it). Bars keep thin 2px gaps and round only their
 * far end. Hover a month for its figure to the cent. Drawn at the
 * container's measured width so text stays 11 px.
 */
import { useState } from "react";

import { monthLabel } from "../../lib/journal-text";
import { compactUsd } from "../../lib/options-text";
import { useMeasuredWidth } from "../../lib/use-measured-width";
import { niceTicks } from "../MultiLine";

interface Props {
  months: { month: string; realized: number }[];
  /** Fallback width before measurement (and in tests). */
  width?: number;
  height?: number;
}

const DEFAULT_WIDTH = 560;
const DEFAULT_HEIGHT = 170;
const PAD_TOP = 10;
const PAD_BOTTOM = 22;
const PAD_RIGHT = 8;
const CHAR_W = 6.7; // ~11 px mono glyph
const GAP = 2; // surface gap between bars
const RADIUS = 4;
const MAX_BAR = 36;

const POS = "#5fbf8a"; // strata-pos
const NEG = "#e57c6e"; // strata-neg
const GRID = "#1f2630"; // strata-line
const AXIS_TEXT = "#5a6473"; // strata-muted
const ZERO_LINE = "#5a6473";
const LABEL_STYLE = { fontSize: 11, fontFamily: "var(--font-mono, monospace)" };

const cents = (v: number) =>
  `${v > 0.004 ? "+" : v < -0.004 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

/** A bar from the zero line to ``top`` or ``bottom``, its far end rounded. */
function barPath(x: number, w: number, zero: number, end: number): string {
  const r = Math.min(RADIUS, w / 2, Math.abs(end - zero));
  if (end <= zero) {
    return `M${x},${zero} V${end + r} Q${x},${end} ${x + r},${end} H${x + w - r} Q${x + w},${end} ${x + w},${end + r} V${zero} Z`;
  }
  return `M${x},${zero} V${end - r} Q${x},${end} ${x + r},${end} H${x + w - r} Q${x + w},${end} ${x + w},${end - r} V${zero} Z`;
}

export function RealizedByMonth({ months, width = DEFAULT_WIDTH, height = DEFAULT_HEIGHT }: Props) {
  const [measureRef, measured] = useMeasuredWidth();
  const [hover, setHover] = useState<number | null>(null);
  if (months.length === 0) return null;

  const values = months.map((m) => m.realized);
  const ticks = niceTicks(Math.min(0, ...values), Math.max(0, ...values));
  const yLo = ticks[0];
  const yHi = ticks[ticks.length - 1];
  const tickLabels = ticks.map((t) => (t === 0 ? "$0" : compactUsd(t)));

  const W = measured ?? width;
  const padLeft = 10 + Math.max(...tickLabels.map((t) => t.length)) * CHAR_W;
  const innerW = Math.max(1, W - padLeft - PAD_RIGHT);
  const plotBottom = height - PAD_BOTTOM;
  const slot = innerW / months.length;
  const barW = Math.max(2, Math.min(MAX_BAR, slot - GAP));
  const xAt = (i: number) => padLeft + (i + 0.5) * slot;
  const yOf = (v: number) => PAD_TOP + (1 - (v - yLo) / (yHi - yLo || 1)) * (plotBottom - PAD_TOP);
  const zero = yOf(0);

  const labelEvery = Math.max(1, Math.ceil((8 * CHAR_W + 8) / slot));
  const hovered = hover === null ? null : months[hover];
  const hoverLeftPct = hover === null ? 0 : (xAt(hover) / W) * 100;

  return (
    <div className="relative" ref={measureRef}>
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${W} ${height}`}
        role="img"
        aria-label={`Realized P&L by month, ${monthLabel(months[0].month)} to ${monthLabel(months[months.length - 1].month)}`}
        className="block"
      >
        {ticks.map((t, i) => (
          <g key={t}>
            {t !== 0 && <line x1={padLeft} x2={W - PAD_RIGHT} y1={yOf(t)} y2={yOf(t)} stroke={GRID} strokeWidth={1} />}
            <text x={padLeft - 6} y={yOf(t) + 3.5} textAnchor="end" fill={AXIS_TEXT} style={LABEL_STYLE}>
              {tickLabels[i]}
            </text>
          </g>
        ))}
        {months.map((m, i) => (
          <path
            key={m.month}
            data-testid="realized-bar"
            data-sign={m.realized >= 0 ? "gain" : "loss"}
            d={barPath(xAt(i) - barW / 2, barW, zero, yOf(m.realized))}
            fill={m.realized >= 0 ? POS : NEG}
            opacity={hover === null || hover === i ? 1 : 0.55}
          />
        ))}
        <line data-testid="realized-zero-line" x1={padLeft} x2={W - PAD_RIGHT} y1={zero} y2={zero} stroke={ZERO_LINE} strokeWidth={1} />
        {months.map((m, i) =>
          i % labelEvery === 0 || i === months.length - 1 ? (
            <text key={m.month} x={xAt(i)} y={height - 6} textAnchor="middle" fill={AXIS_TEXT} style={LABEL_STYLE}>
              {monthLabel(m.month)}
            </text>
          ) : null,
        )}
        {months.map((m, i) => (
          <rect
            key={m.month}
            data-testid="realized-hit"
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
          data-testid="realized-tooltip"
          className="pointer-events-none absolute top-0 z-10 rounded-md border border-strata-border bg-strata-raise px-2.5 py-1.5 font-mono text-[11px] text-strata-fg shadow-sm"
          style={{ left: `${hoverLeftPct}%`, transform: hoverLeftPct > 55 ? "translateX(calc(-100% - 10px))" : "translateX(10px)" }}
        >
          <div className="mb-0.5 text-strata-dim">{monthLabel(hovered.month)}</div>
          <div className="tabular whitespace-nowrap text-strata-hi">{cents(hovered.realized)} realized</div>
        </div>
      )}
    </div>
  );
}
