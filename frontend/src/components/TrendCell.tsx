/**
 * TrendCell — the "Trend" column of claim tables (QualityCard,
 * ReportRenderer). 2026-11, tasks/dogfood-2026-11.md #10.
 *
 * A bare autoscaled sparkline implied trends the data can't support:
 * ROIC / ROE carry only 2 points, so their "falling" line was two dots
 * joined, and min–max scaling made a 3-point move look like a crash. The
 * cell now says what changed since the first period, in the claim's own
 * terms, and only draws a line when there are at least 3 points:
 *
 *   - fraction / percent claims → percentage points ("▼ 6.6 pts")
 *   - other units → percent change ("▲ 43%"), or the absolute move when
 *     the starting value is zero or negative (a % of a loss misleads)
 *   - an unchanged series reads "flat"
 */
import { formatClaimValue } from "../lib/format";
import type { ClaimHistoryPoint, ClaimUnit } from "../lib/schemas";
import { Sparkline } from "./Sparkline";

interface Props {
  history: ClaimHistoryPoint[];
  unit?: ClaimUnit | null;
  label?: string;
}

const MIN_POINTS_FOR_LINE = 3;

function describeChange(first: number, last: number, unit?: ClaimUnit | null): string {
  if (unit === "fraction" || unit === "percent" || unit === "percentage_points") {
    const pts = (last - first) * (unit === "percent" ? 1 : 100);
    if (Math.abs(pts) < 0.05) return "flat";
    return `${pts > 0 ? "▲" : "▼"} ${Math.abs(pts).toFixed(1)} pts`;
  }
  if (first > 0) {
    const pct = (last / first - 1) * 100;
    if (Math.abs(pct) < 0.5) return "flat";
    return `${pct > 0 ? "▲" : "▼"} ${Math.abs(pct).toFixed(0)}%`;
  }
  const diff = last - first;
  if (diff === 0) return "flat";
  return `${diff > 0 ? "▲" : "▼"} ${formatClaimValue(Math.abs(diff), unit)}`;
}

export function TrendCell({ history, unit, label }: Props) {
  if (history.length < 2) return null;
  const sorted = [...history].sort((a, b) => (a.period < b.period ? -1 : 1));
  const first = sorted[0];
  const last = sorted[sorted.length - 1];
  const drawLine = sorted.length >= MIN_POINTS_FOR_LINE;

  return (
    <div className="flex items-center gap-2">
      {drawLine && (
        <Sparkline history={sorted} width={64} height={22} ariaLabel={label ? `Trend for ${label}` : undefined} />
      )}
      <div className="font-mono text-[10px] leading-tight">
        <div data-testid="trend-delta" className="tabular text-strata-fg">
          {describeChange(first.value, last.value, unit)}
        </div>
        {drawLine ? (
          <div data-testid="trend-since" className="text-strata-muted">
            since {first.period}
          </div>
        ) : (
          <div data-testid="trend-sparse" className="text-strata-muted">
            {sorted.length} periods only
          </div>
        )}
      </div>
    </div>
  );
}
