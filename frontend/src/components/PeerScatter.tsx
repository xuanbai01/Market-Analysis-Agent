/**
 * PeerScatter — 2-D peer-comparison scatter for the Peers section.
 * Phase 3.3.C.
 *
 * Three visual layers:
 *
 * 1. **Peer dots** (slate-500, 6 px) — one per peer with both
 *    metrics. Labeled on hover via the tooltip.
 * 2. **Subject dot** (slate-900, 9 px) — the report's own ticker;
 *    visually distinct via fill + size. Always labeled.
 * 3. **Median cross** (slate-400, smaller cross marker) — the
 *    aggregate from the existing ``median.*`` claims; visual anchor
 *    for "where does the cluster sit." Drawn third so it sits below
 *    the subject dot in z-order (Recharts renders later <Scatter>
 *    on top).
 *
 * ## Why explicit dimensions, no ResponsiveContainer
 *
 * Same lesson as Sparkline / SectionChart: ResponsiveContainer
 * relies on getBoundingClientRect which is 0 in happy-dom and flaky
 * in nested layouts. Default 360×240; caller can override.
 *
 * ## Why a default export
 *
 * ReportRenderer lazy-loads this component via React.lazy() so
 * recharts stays out of the main bundle. lazy() requires a default
 * export.
 */
import {
  CartesianGrid,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

import { formatClaimValue } from "../lib/format";
import type {
  MedianPoint,
  PeerRow,
  SubjectPoint,
} from "../lib/peer-grouping";

interface Props {
  peers: PeerRow[];
  subject?: SubjectPoint;
  median?: MedianPoint;
  width?: number;
  height?: number;
}

const DEFAULT_WIDTH = 360;
const DEFAULT_HEIGHT = 240;

const PEER_FILL = "rgb(100, 116, 139)"; // slate-500
const SUBJECT_FILL = "rgb(15, 23, 42)"; // slate-900
const MEDIAN_FILL = "rgb(148, 163, 184)"; // slate-400

interface PeerDatum {
  symbol: string;
  pe: number;
  margin: number;
}

const tooltipFormatter = (value: unknown, name: string) => {
  if (typeof value !== "number") return [String(value), name];
  // P/E is a multiple (no percent suffix), gross margin is a fraction
  // [-1, 1] (formatClaimValue auto-percents).
  return [formatClaimValue(value), name];
};

const labelFormatter = (
  _label: unknown,
  payload: Array<{ payload?: PeerDatum }>,
) => {
  const datum = payload?.[0]?.payload;
  return datum?.symbol ?? "";
};

export default function PeerScatter({
  peers,
  subject,
  median,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
}: Props) {
  // Scatter without peers makes no sense — the comparison needs a
  // cluster to compare to. Subject + median alone don't justify the
  // chart; fall back to the existing claims table.
  if (peers.length === 0) return null;

  const subjectData: PeerDatum[] = subject ? [subject] : [];
  const medianData: PeerDatum[] = median
    ? [{ symbol: "median", pe: median.pe, margin: median.margin }]
    : [];

  return (
    <div data-testid="peer-scatter-wrapper" className="hidden sm:block">
      <ScatterChart
        data-testid="peer-scatter"
        width={width}
        height={height}
        margin={{ top: 8, right: 8, bottom: 4, left: 0 }}
      >
        <CartesianGrid stroke="rgb(241, 245, 249)" /* slate-100 */ />
        <XAxis
          type="number"
          dataKey="pe"
          name="P/E"
          tick={{ fontSize: 10, fill: "rgb(100, 116, 139)" }}
          tickLine={false}
          axisLine={{ stroke: "rgb(226, 232, 240)" }}
          tickFormatter={(v: number) => formatClaimValue(v)}
        />
        <YAxis
          type="number"
          dataKey="margin"
          name="Gross margin"
          tick={{ fontSize: 10, fill: "rgb(100, 116, 139)" }}
          tickLine={false}
          axisLine={{ stroke: "rgb(226, 232, 240)" }}
          tickFormatter={(v: number) => formatClaimValue(v)}
          width={48}
        />
        <ZAxis range={[60, 120]} />
        <Tooltip
          formatter={tooltipFormatter}
          labelFormatter={labelFormatter}
          contentStyle={{
            fontSize: 11,
            borderRadius: 4,
            border: "1px solid rgb(226, 232, 240)",
          }}
        />
        <Scatter
          name="peers"
          data={peers}
          fill={PEER_FILL}
          isAnimationActive={false}
        />
        {medianData.length > 0 && (
          <Scatter
            name="median"
            data={medianData}
            fill={MEDIAN_FILL}
            shape="cross"
            isAnimationActive={false}
          />
        )}
        {subjectData.length > 0 && (
          <Scatter
            name="subject"
            data={subjectData}
            fill={SUBJECT_FILL}
            shape="circle"
            isAnimationActive={false}
          />
        )}
      </ScatterChart>
    </div>
  );
}
