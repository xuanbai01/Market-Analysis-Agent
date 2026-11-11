/**
 * Formatters for chart axes, end labels and hover readouts (2026-11
 * readable-charts pass, tasks/dogfood-2026-11.md #8–#10). Ticks drop
 * needless decimals ("$2", "20%"); values keep the precision the cards
 * show elsewhere ("$2.62", "66.2%").
 */

function trimmed(n: number, decimals: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(decimals);
}

/** "2025-Q3" → "Q3 '25"; other period shapes pass through. */
export function shortPeriod(period: string): string {
  const m = /^(\d{4})-Q([1-4])$/.exec(period);
  return m ? `Q${m[2]} '${m[1].slice(2)}` : period;
}

/** Dollars per share: "$2.62", "-$0.55". */
export function usdPerShare(v: number): string {
  return `${v < 0 ? "-" : ""}$${Math.abs(v).toFixed(2)}`;
}

/** Dollar axis tick: "$0", "$2", "$2.50". */
export function usdTick(v: number): string {
  return `${v < 0 ? "-" : ""}$${trimmed(Math.abs(v), 2)}`;
}

/** A stored fraction as a percent value: 0.6624 → "66.2%". */
export function fractionPct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

/** A stored fraction as a percent tick: 0.2 → "20%", -0.25 → "-25%". */
export function fractionPctTick(v: number): string {
  return `${trimmed(Number((v * 100).toFixed(2)), 1)}%`;
}

/** Indexed value (first period = 100): 236.4 → "236". */
export function indexValue(v: number): string {
  return v.toFixed(0);
}

/** Period-over-period change of a level: "+18% QoQ", or the absolute
 *  move when the prior value is zero/negative (a % of a loss misleads).
 *  ``period`` names the step: "QoQ" for quarters, "YoY" for years. */
export function relativeChange(format: (v: number) => string, period = "QoQ") {
  return (now: number, prev: number): string => {
    if (prev > 0) {
      const pct = (now / prev - 1) * 100;
      return `${pct >= 0 ? "+" : ""}${pct.toFixed(0)}% ${period}`;
    }
    const diff = now - prev;
    return `${diff >= 0 ? "+" : "-"}${format(Math.abs(diff))} ${period}`;
  };
}

/** Change of a rate in percentage points: "+1.9 pts QoQ". */
export function pointsChange(now: number, prev: number): string {
  const pts = (now - prev) * 100;
  return `${pts >= 0 ? "+" : ""}${pts.toFixed(1)} pts QoQ`;
}
