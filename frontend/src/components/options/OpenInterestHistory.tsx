/**
 * OpenInterestHistory — calls and puts open across every listed expiry,
 * one point a session, from our own daily run (option_oi_totals). Drawn
 * once two whole reads are stored; the panel's sentence carries the first.
 * A session read short is left out (it would draw as a drop) and counted.
 */
import type { OpenInterestTotal } from "../../lib/options-schemas";
import { compactCount, dateLabel, wholeRead } from "../../lib/options-text";
import { MultiLine } from "../MultiLine";
import { COLOR } from "./chart-kit";

export function OpenInterestHistory({ history }: { history: OpenInterestTotal[] }) {
  const whole = history.filter(wholeRead);
  if (whole.length < 2) return null;
  const short = history.length - whole.length;
  return (
    <div data-testid="options-oi-history" className="w-full">
      <MultiLine
        series={[
          { label: "Calls", color: COLOR.call, history: whole.map((h) => ({ period: h.date, value: h.call })) },
          { label: "Puts", color: COLOR.put, history: whole.map((h) => ({ period: h.date, value: h.put })) },
        ]}
        showLegend
        showEndLabels
        formatValue={compactCount}
        formatPeriod={(p) => dateLabel(p)}
        ariaLabel={`Open interest across all expiries, ${whole.length} sessions, calls and puts.`}
      />
      {short > 0 && (
        <p className="mt-2 font-mono text-[10px] text-strata-muted">
          {short === 1 ? "1 session read short is" : `${short} sessions read short are`} left out of the lines.
        </p>
      )}
    </div>
  );
}
