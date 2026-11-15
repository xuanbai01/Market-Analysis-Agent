/**
 * OpenInterestHistory — calls and puts open across every listed expiry,
 * one point a session, from our own daily run (option_oi_totals). Drawn
 * once two sessions are stored; the panel's sentence carries the first.
 */
import type { OpenInterestTotal } from "../../lib/options-schemas";
import { compactCount, dateLabel } from "../../lib/options-text";
import { MultiLine } from "../MultiLine";
import { COLOR } from "./chart-kit";

export function OpenInterestHistory({ history }: { history: OpenInterestTotal[] }) {
  if (history.length < 2) return null;
  return (
    <div data-testid="options-oi-history" className="w-full">
      <MultiLine
        series={[
          { label: "Calls", color: COLOR.call, history: history.map((h) => ({ period: h.date, value: h.call })) },
          { label: "Puts", color: COLOR.put, history: history.map((h) => ({ period: h.date, value: h.put })) },
        ]}
        showLegend
        showEndLabels
        formatValue={compactCount}
        formatPeriod={(p) => dateLabel(p)}
        ariaLabel={`Open interest across all expiries, ${history.length} sessions, calls and puts.`}
      />
    </div>
  );
}
