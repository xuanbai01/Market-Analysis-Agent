/**
 * PeerScatterV2 — hand-rolled SVG peer scatter with selectable axis
 * presets. Phase 4.2.
 *
 * Replaces the 3.3.C Recharts ``ScatterChart`` with a much smaller
 * SVG implementation that:
 *
 *   - matches the Strata dark-theme styling out of the box
 *   - supports pivoting axes via 3 inline preset pills (no dropdown
 *     because the choice is small enough that 3 visible buttons read
 *     better than a hidden menu)
 *   - drops the recharts dep for this component (the shared chunk
 *     remains for SectionChart until 4.3 replaces it)
 *
 * The 3 axis presets are all drawn from ``PEER_METRICS`` on the
 * backend (``trailing_pe``, ``p_s``, ``ev_ebitda``, ``gross_margin``)
 * so 4.2 needs no backend change. Operating margin / ROIC axes come
 * back if 4.5/4.8 dogfooding asks for them — that requires extending
 * ``app/services/peers.py::PEER_METRICS`` first.
 *
 * ## Visual layers (z-order, bottom to top)
 *
 *   1. Faint horizontal + vertical grid lines (min/mid/max each axis)
 *   2. Peer dots (small, strata-muted color)
 *   3. Median cross (faint cross at peer-median (x, y))
 *   4. Subject dot (larger, strata-peers accent, with ticker label)
 *   5. Axis labels along left + bottom edges
 */
import { useState } from "react";

import { formatClaimValue } from "../lib/format";
import {
  extractMedianForAxes,
  groupPeersForAxes,
} from "../lib/peer-grouping";
import type { Claim } from "../lib/schemas";

// ── Axis presets ─────────────────────────────────────────────────────

interface Preset {
  id: "pe-gm" | "ps-gm" | "ev-gm";
  label: string;
  xMetric: string;
  yMetric: string;
  xShort: string;
  yShort: string;
}

const PRESETS: Preset[] = [
  {
    id: "pe-gm",
    label: "P/E × Gross Margin",
    xMetric: "P/E ratio (trailing 12 months)",
    yMetric: "Gross margin",
    xShort: "P/E TTM",
    yShort: "Gross margin",
  },
  {
    id: "ps-gm",
    label: "P/S × Gross Margin",
    xMetric: "Price-to-sales ratio (trailing 12 months)",
    yMetric: "Gross margin",
    xShort: "P/S TTM",
    yShort: "Gross margin",
  },
  {
    id: "ev-gm",
    label: "EV/EBITDA × Gross Margin",
    xMetric: "Enterprise value to EBITDA",
    yMetric: "Gross margin",
    xShort: "EV/EBITDA",
    yShort: "Gross margin",
  },
];

// Narrowed to the numeric subject keys (excludes ``symbol``) so TS
// knows the lookup returns ``number | null``, never a string.
type NumericSubjectKey = "trailing_pe" | "p_s" | "ev_ebitda";

const SUBJECT_KEY_FOR_X: Record<Preset["id"], NumericSubjectKey> = {
  "pe-gm": "trailing_pe",
  "ps-gm": "p_s",
  "ev-gm": "ev_ebitda",
};

// ── Subject shape ────────────────────────────────────────────────────

export interface SubjectPoint {
  symbol: string;
  trailing_pe: number | null;
  p_s: number | null;
  ev_ebitda: number | null;
  gross_margin: number | null;
}

interface Props {
  peerClaims: readonly Claim[];
  subject?: SubjectPoint;
  width?: number;
  height?: number;
}

// ── Geometry ─────────────────────────────────────────────────────────

const DEFAULT_WIDTH = 500;
const DEFAULT_HEIGHT = 300;
const PADDING_TOP = 8;
const PADDING_BOTTOM = 28;
const PADDING_LEFT = 48;
const PADDING_RIGHT = 16;

const PEER_FILL = "rgb(105, 113, 130)"; // strata-muted-ish
const SUBJECT_FILL = "rgb(155, 141, 219)"; // strata-peers
const MEDIAN_STROKE = "rgb(126, 154, 212)"; // strata-highlight
const GRID_COLOR = "rgb(31, 38, 48)"; // strata-line
const AXIS_LABEL_COLOR = "rgb(90, 100, 115)"; // strata-muted

export function PeerScatterV2({
  peerClaims,
  subject,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
}: Props) {
  const [presetId, setPresetId] = useState<Preset["id"]>("pe-gm");
  const preset = PRESETS.find((p) => p.id === presetId) ?? PRESETS[0];

  const peerRows = groupPeersForAxes(
    peerClaims,
    preset.xMetric,
    preset.yMetric,
  );
  const median = extractMedianForAxes(
    peerClaims,
    preset.xMetric,
    preset.yMetric,
  );

  // Subject's (x, y) for the active preset.
  const subjectX = subject ? subject[SUBJECT_KEY_FOR_X[preset.id]] : null;
  const subjectY = subject ? subject.gross_margin : null;
  const subjectPoint =
    subjectX !== null && subjectY !== null && subject
      ? { symbol: subject.symbol, x: subjectX, y: subjectY }
      : null;

  // Bail out completely when no peer dots can render — the chart is
  // meaningless without a peer cluster.
  if (peerRows.length === 0 && !subjectPoint) {
    return null;
  }

  // Build axis ranges across peers + subject + median so every point
  // sits inside the plotted area.
  const xs: number[] = peerRows.map((r) => r.x);
  const ys: number[] = peerRows.map((r) => r.y);
  if (subjectPoint) {
    xs.push(subjectPoint.x);
    ys.push(subjectPoint.y);
  }
  if (median) {
    xs.push(median.x);
    ys.push(median.y);
  }
  const xMin = Math.min(...xs);
  const xMax = Math.max(...xs);
  const yMin = Math.min(...ys);
  const yMax = Math.max(...ys);
  const xPad = (xMax - xMin || 1) * 0.1;
  const yPad = (yMax - yMin || 1) * 0.1;
  const xLo = xMin - xPad;
  const xHi = xMax + xPad;
  const yLo = yMin - yPad;
  const yHi = yMax + yPad;

  const innerW = width - PADDING_LEFT - PADDING_RIGHT;
  const innerH = height - PADDING_TOP - PADDING_BOTTOM;

  function xOf(v: number): number {
    return PADDING_LEFT + ((v - xLo) / (xHi - xLo || 1)) * innerW;
  }
  function yOf(v: number): number {
    return PADDING_TOP + (1 - (v - yLo) / (yHi - yLo || 1)) * innerH;
  }

  return (
    <div className="hidden sm:block">
      {/* Preset pills. */}
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="font-mono text-[10px] uppercase tracking-kicker text-strata-peers">
          Peer scatter
        </span>
        <div className="flex gap-1 font-mono text-xs">
          {PRESETS.map((p) => (
            <button
              key={p.id}
              type="button"
              data-pill="peer-axis-preset"
              onClick={() => setPresetId(p.id)}
              className={`rounded px-2 py-0.5 transition ${
                p.id === preset.id
                  ? "bg-strata-peers text-strata-canvas"
                  : "text-strata-dim hover:text-strata-fg"
              }`}
              aria-pressed={p.id === preset.id}
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      <svg
        data-testid="peer-scatter-v2"
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`Peer scatter, ${preset.label}`}
        className="block"
      >
        {/* Plot-area frame. */}
        <line
          x1={PADDING_LEFT}
          x2={PADDING_LEFT}
          y1={PADDING_TOP}
          y2={height - PADDING_BOTTOM}
          stroke={GRID_COLOR}
          strokeWidth={1}
        />
        <line
          x1={PADDING_LEFT}
          x2={width - PADDING_RIGHT}
          y1={height - PADDING_BOTTOM}
          y2={height - PADDING_BOTTOM}
          stroke={GRID_COLOR}
          strokeWidth={1}
        />

        {/* Peer dots. */}
        {peerRows.map((r) => (
          <g key={`peer-${r.symbol}`}>
            <circle
              data-marker="peer"
              data-symbol={r.symbol}
              cx={xOf(r.x)}
              cy={yOf(r.y)}
              r={4}
              fill={PEER_FILL}
              fillOpacity={0.85}
            />
            <text
              x={xOf(r.x) + 6}
              y={yOf(r.y) + 3}
              fill={AXIS_LABEL_COLOR}
              style={{ fontSize: 9, fontFamily: "var(--font-mono, monospace)" }}
            >
              {r.symbol}
            </text>
          </g>
        ))}

        {/* Median cross. */}
        {median && (
          <g data-marker="median">
            <line
              x1={xOf(median.x) - 5}
              x2={xOf(median.x) + 5}
              y1={yOf(median.y)}
              y2={yOf(median.y)}
              stroke={MEDIAN_STROKE}
              strokeWidth={1.5}
            />
            <line
              x1={xOf(median.x)}
              x2={xOf(median.x)}
              y1={yOf(median.y) - 5}
              y2={yOf(median.y) + 5}
              stroke={MEDIAN_STROKE}
              strokeWidth={1.5}
            />
          </g>
        )}

        {/* Subject dot. */}
        {subjectPoint && (
          <g data-marker="subject">
            <circle
              cx={xOf(subjectPoint.x)}
              cy={yOf(subjectPoint.y)}
              r={6.5}
              fill={SUBJECT_FILL}
              stroke="rgb(245, 247, 251)"
              strokeWidth={1.5}
            />
            <text
              x={xOf(subjectPoint.x) + 9}
              y={yOf(subjectPoint.y) + 4}
              fill="rgb(245, 247, 251)"
              style={{
                fontSize: 11,
                fontFamily: "var(--font-mono, monospace)",
                fontWeight: 500,
              }}
            >
              {subjectPoint.symbol}
            </text>
          </g>
        )}

        {/* X-axis ticks: min + max. */}
        <text
          x={PADDING_LEFT}
          y={height - 8}
          fill={AXIS_LABEL_COLOR}
          style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)" }}
        >
          {formatClaimValue(xLo)}
        </text>
        <text
          x={width - PADDING_RIGHT}
          y={height - 8}
          fill={AXIS_LABEL_COLOR}
          textAnchor="end"
          style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)" }}
        >
          {formatClaimValue(xHi)}
        </text>

        {/* Y-axis ticks: min + max. */}
        <text
          x={PADDING_LEFT - 4}
          y={height - PADDING_BOTTOM}
          fill={AXIS_LABEL_COLOR}
          textAnchor="end"
          style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)" }}
        >
          {formatClaimValue(yLo)}
        </text>
        <text
          x={PADDING_LEFT - 4}
          y={PADDING_TOP + 8}
          fill={AXIS_LABEL_COLOR}
          textAnchor="end"
          style={{ fontSize: 10, fontFamily: "var(--font-mono, monospace)" }}
        >
          {formatClaimValue(yHi)}
        </text>

        {/* Axis titles. */}
        <text
          x={(width + PADDING_LEFT) / 2}
          y={height - 1}
          fill={AXIS_LABEL_COLOR}
          textAnchor="middle"
          style={{
            fontSize: 10,
            fontFamily: "var(--font-mono, monospace)",
            letterSpacing: "0.18em",
            textTransform: "uppercase",
          }}
        >
          {preset.xShort}
        </text>
        <text
          x={10}
          y={(height - PADDING_BOTTOM + PADDING_TOP) / 2}
          fill={AXIS_LABEL_COLOR}
          textAnchor="middle"
          transform={`rotate(-90 10 ${(height - PADDING_BOTTOM + PADDING_TOP) / 2})`}
          style={{
            fontSize: 10,
            fontFamily: "var(--font-mono, monospace)",
            letterSpacing: "0.18em",
            textTransform: "uppercase",
          }}
        >
          {preset.yShort}
        </text>
      </svg>
    </div>
  );
}
