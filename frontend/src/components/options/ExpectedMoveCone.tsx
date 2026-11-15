/**
 * ExpectedMoveCone — where option prices put one standard deviation of the
 * stock by each expiry: forward · e^(±IV·√T), out to about six months, on
 * a square-root day scale. The report's reaction day is marked.
 */
import { useState } from "react";

import type { ExpirySummary } from "../../lib/options-schemas";
import { niceTicks } from "../MultiLine";
import { AxisText, COLOR, DAY_TICKS, PAD, Tooltip, YGrid, linear, money, pct, shortDate, sqrtDays, useChartWidth } from "./chart-kit";
import { conePoints, drawsCone } from "./draws";

const HEIGHT = 260;

interface Props {
  expiries: ExpirySummary[];
  spot: number;
  eventDays: number | null;
}

export function ExpectedMoveCone({ expiries, spot, eventDays }: Props) {
  const [ref, W] = useChartWidth();
  const [hover, setHover] = useState<number | null>(null);
  if (!drawsCone(expiries)) return null;
  const points = conePoints(expiries);

  const maxDays = points[points.length - 1].days;
  const x = sqrtDays(maxDays, PAD.left, W - PAD.right);
  const ticks = niceTicks(Math.min(spot, ...points.map((p) => p.low)), Math.max(spot, ...points.map((p) => p.high)));
  const y = linear(ticks[0], ticks[ticks.length - 1], HEIGHT - PAD.bottom, PAD.top);
  const band =
    `M${x(0)},${y(spot)} ` +
    points.map((p) => `L${x(p.days)},${y(p.high)}`).join(" ") +
    " " +
    [...points].reverse().map((p) => `L${x(p.days)},${y(p.low)}`).join(" ") +
    " Z";
  const centre = `M${x(0)},${y(spot)} ` + points.map((p) => `L${x(p.days)},${y(p.forward)}`).join(" ");
  const edges = points.map((p) => x(p.days));
  const first = points[0];
  const last = points[points.length - 1];
  const shown = hover === null ? null : points[hover];

  return (
    <div ref={ref} className="relative w-full overflow-x-auto" data-testid="options-cone">
      <svg
        width={W}
        height={HEIGHT}
        viewBox={`0 0 ${W} ${HEIGHT}`}
        role="img"
        aria-label={`Expected move by expiry: ±${pct(first.expected_move)} by ${first.expiry}, ±${pct(last.expected_move)} by ${last.expiry}.`}
        onMouseLeave={() => setHover(null)}
      >
        <YGrid ticks={ticks} y={y} x0={PAD.left} x1={W - PAD.right} format={(v) => `$${Math.round(v)}`} />
        {DAY_TICKS.filter((d) => d <= maxDays).map((d) => (
          <AxisText key={d} x={x(d)} y={HEIGHT - 8} anchor="middle">
            {`${d}d`}
          </AxisText>
        ))}
        <path data-testid="options-cone-band" d={band} fill={COLOR.band} fillOpacity={0.16} stroke={COLOR.band} strokeOpacity={0.5} strokeWidth={1} />
        <path d={centre} fill="none" stroke={COLOR.hi} strokeWidth={1.5} />
        {eventDays !== null && eventDays <= maxDays && (
          <g data-testid="options-cone-event">
            <line x1={x(eventDays)} x2={x(eventDays)} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke={COLOR.axis} strokeDasharray="4 3" />
            <AxisText x={x(eventDays) + 4} y={PAD.top + 10} anchor="start">
              report
            </AxisText>
          </g>
        )}
        {hover !== null && (
          <line x1={edges[hover]} x2={edges[hover]} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke={COLOR.axis} strokeWidth={1} />
        )}
        {points.map((p, i) => {
          const left = i === 0 ? PAD.left : (edges[i - 1] + edges[i]) / 2;
          const right = i === points.length - 1 ? W - PAD.right : (edges[i] + edges[i + 1]) / 2;
          return (
            <rect
              key={p.expiry}
              data-testid="options-cone-hit"
              x={left}
              y={PAD.top}
              width={Math.max(1, right - left)}
              height={HEIGHT - PAD.top - PAD.bottom}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
            />
          );
        })}
      </svg>
      {shown && hover !== null && (
        <Tooltip testId="options-cone-tooltip" left={edges[hover]} width={W}>
          <p className="text-strata-hi">
            {shortDate(shown.expiry)} · {Math.round(shown.days)} days
          </p>
          <p className="text-strata-dim">
            IV {pct(shown.atm_iv)} · ±{pct(shown.expected_move)}
          </p>
          <p>
            {money(shown.low)} – {money(shown.high)}
          </p>
          {shown.straddle !== null && <p className="text-strata-dim">straddle {money(shown.straddle)}</p>}
        </Tooltip>
      )}
    </div>
  );
}
