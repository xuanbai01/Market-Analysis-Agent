/**
 * TermStructureChart — at-the-money IV by days to expiry (square-root
 * scale), with 20-session realized volatility as a reference line on the
 * same axis. Expiries that include the next report are hollow.
 */
import { useState } from "react";

import type { ExpirySummary } from "../../lib/options-schemas";
import { niceTicks } from "../MultiLine";
import { AxisText, COLOR, DAY_TICKS, FONT, PAD, Tooltip, YGrid, linear, pct, shortDate, sqrtDays, useChartWidth } from "./chart-kit";
import { drawsTerm } from "./draws";

const HEIGHT = 240;

export function TermStructureChart({ expiries, rv20 }: { expiries: ExpirySummary[]; rv20: number | null }) {
  const [ref, W] = useChartWidth();
  const [hover, setHover] = useState<number | null>(null);
  if (!drawsTerm(expiries)) return null;
  const points = [...expiries].sort((a, b) => a.days - b.days);

  const maxDays = points[points.length - 1].days;
  const x = sqrtDays(maxDays, PAD.left, W - PAD.right - 60);
  const values = [...points.map((p) => p.atm_iv), ...(rv20 === null ? [] : [rv20])];
  const ticks = niceTicks(Math.min(...values) * 0.9, Math.max(...values) * 1.05);
  const y = linear(ticks[0], ticks[ticks.length - 1], HEIGHT - PAD.bottom, PAD.top);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(p.days)},${y(p.atm_iv)}`).join(" ");
  const shown = hover === null ? null : points[hover];
  const hasEarnings = points.some((p) => p.includes_earnings);

  return (
    <div ref={ref} className="relative w-full overflow-x-auto" data-testid="options-term">
      <svg
        width={W}
        height={HEIGHT}
        viewBox={`0 0 ${W} ${HEIGHT}`}
        role="img"
        aria-label={`At-the-money IV by expiry, from ${pct(points[0].atm_iv)} at ${Math.round(points[0].days)} days to ${pct(points[points.length - 1].atm_iv)} at ${Math.round(maxDays)} days.`}
        onMouseLeave={() => setHover(null)}
      >
        <YGrid ticks={ticks} y={y} x0={PAD.left} x1={W - PAD.right - 60} format={(v) => pct(v, 0)} />
        {DAY_TICKS.filter((d) => d <= maxDays).map((d) => (
          <AxisText key={d} x={x(d)} y={HEIGHT - 8} anchor="middle">
            {`${d}d`}
          </AxisText>
        ))}
        {rv20 !== null && (
          <g data-testid="options-term-rv">
            <line x1={PAD.left} x2={W - PAD.right - 60} y1={y(rv20)} y2={y(rv20)} stroke={COLOR.axis} strokeDasharray="4 3" />
            <text x={W - PAD.right - 56} y={y(rv20) + 4} fontSize={11} fill={COLOR.ink} fontFamily={FONT}>
              {`RV20 ${pct(rv20)}`}
            </text>
          </g>
        )}
        <path d={line} fill="none" stroke={COLOR.band} strokeWidth={2} />
        {points.map((p, i) => (
          <circle
            key={p.expiry}
            data-testid="options-term-dot"
            data-earnings={p.includes_earnings ? "true" : "false"}
            cx={x(p.days)}
            cy={y(p.atm_iv)}
            r={hover === i ? 5 : 4}
            fill={p.includes_earnings ? COLOR.surface : COLOR.band}
            stroke={COLOR.band}
            strokeWidth={2}
          />
        ))}
        {points.map((p, i) => (
          <rect
            key={`hit-${p.expiry}`}
            data-testid="options-term-hit"
            x={x(p.days) - 10}
            y={PAD.top}
            width={20}
            height={HEIGHT - PAD.top - PAD.bottom}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>
      {hasEarnings && (
        <p className="mt-1 font-mono text-[10px] text-strata-muted">Hollow: the expiry includes the next earnings report.</p>
      )}
      {shown && hover !== null && (
        <Tooltip testId="options-term-tooltip" left={x(shown.days)} width={W}>
          <p className="text-strata-hi">
            {shortDate(shown.expiry)} · {Math.round(shown.days)} days
          </p>
          <p>IV {pct(shown.atm_iv)}</p>
          {shown.includes_earnings && <p className="text-strata-dim">includes the report</p>}
        </Tooltip>
      )}
    </div>
  );
}
