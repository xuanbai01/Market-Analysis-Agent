/**
 * SectionChart — the larger "headline" chart at the top of a section
 * card. Phase 3.3.B.
 *
 * Renders the primary Claim's ``history`` as a slate-700 line; when a
 * secondary Claim is provided (Earnings actual vs estimate today),
 * renders it as a dashed slate-400 line on the same axis.
 *
 * ## Why explicit width/height (no ResponsiveContainer)
 *
 * Same lesson as Sparkline: Recharts' ``ResponsiveContainer`` relies
 * on ``getBoundingClientRect`` which returns 0 in happy-dom and
 * silently fails in some nested-container layouts. Taking ``width`` /
 * ``height`` as explicit props sidesteps both. The default 300×120
 * fits a section card; callers can override on a wider layout if
 * needed.
 *
 * ## Why we reuse formatClaimValue for tick labels
 *
 * ``formatClaimValue`` already encodes the percent-vs-currency-vs-
 * abbreviated-magnitude rules used in the claims-table cells and
 * (importantly) in the eval rubric on the backend. Reusing it here
 * means the chart's Y-axis ticks read the same as the claim's headline
 * value and the same as what the rubric checks against — single source
 * of truth.
 *
 * ## Period axis anchoring
 *
 * When the user passes a secondary Claim, we anchor on the primary's
 * period axis: each row is ``{period, primary, secondary?}`` and any
 * secondary period not covered by primary's history is dropped, while
 * any primary period not covered by secondary gets ``secondary: null``
 * so Recharts draws a gap. This handles the common case (eps_actual
 * and eps_estimate align on quarter dates) without crashing on the
 * rare misaligned case.
 */
import {
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatClaimValue } from "../lib/format";
import type { Claim } from "../lib/schemas";

interface Props {
  primary: Claim;
  secondary?: Claim;
  width?: number;
  height?: number;
}

interface Row {
  period: string;
  primary: number;
  secondary?: number | null;
}

const DEFAULT_WIDTH = 300;
const DEFAULT_HEIGHT = 120;
const PRIMARY_STROKE = "rgb(51, 65, 85)"; // slate-700
const SECONDARY_STROKE = "rgb(148, 163, 184)"; // slate-400

function buildRows(primary: Claim, secondary?: Claim): Row[] {
  const secondaryByPeriod = new Map<string, number>();
  if (secondary) {
    for (const p of secondary.history) {
      secondaryByPeriod.set(p.period, p.value);
    }
  }
  return primary.history.map((p) => {
    const row: Row = { period: p.period, primary: p.value };
    if (secondary) {
      row.secondary = secondaryByPeriod.get(p.period) ?? null;
    }
    return row;
  });
}

export default function SectionChart({
  primary,
  secondary,
  width = DEFAULT_WIDTH,
  height = DEFAULT_HEIGHT,
}: Props) {
  // Defense-in-depth: featuredClaim() also gates on >= 2 points, but
  // direct callers (or tests) might hand us a degenerate primary.
  if (primary.history.length < 2) return null;

  const rows = buildRows(primary, secondary);

  return (
    <div data-testid="section-chart-wrapper" className="hidden sm:block">
      <LineChart
        data-testid="section-chart"
        width={width}
        height={height}
        data={rows}
        margin={{ top: 8, right: 8, bottom: 4, left: 0 }}
      >
        <XAxis
          dataKey="period"
          tick={{ fontSize: 10, fill: "rgb(100, 116, 139)" /* slate-500 */ }}
          interval="preserveStartEnd"
          tickLine={false}
          axisLine={{ stroke: "rgb(226, 232, 240)" /* slate-200 */ }}
        />
        <YAxis
          tick={{ fontSize: 10, fill: "rgb(100, 116, 139)" /* slate-500 */ }}
          tickFormatter={(v: number) => formatClaimValue(v)}
          tickLine={false}
          axisLine={{ stroke: "rgb(226, 232, 240)" /* slate-200 */ }}
          width={48}
        />
        <Tooltip
          formatter={(v: unknown) =>
            typeof v === "number" ? formatClaimValue(v) : String(v)
          }
          labelFormatter={(p) => p}
          contentStyle={{
            fontSize: 11,
            borderRadius: 4,
            border: "1px solid rgb(226, 232, 240)",
          }}
        />
        <Line
          type="monotone"
          dataKey="primary"
          name={primary.description}
          stroke={PRIMARY_STROKE}
          strokeWidth={1.5}
          dot={false}
          isAnimationActive={false}
        />
        {secondary && (
          <Line
            type="monotone"
            dataKey="secondary"
            name={secondary.description}
            stroke={SECONDARY_STROKE}
            strokeWidth={1.5}
            strokeDasharray="3 3"
            dot={false}
            isAnimationActive={false}
            connectNulls={false}
          />
        )}
      </LineChart>
    </div>
  );
}
