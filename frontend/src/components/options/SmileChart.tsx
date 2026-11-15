/**
 * SmileChart — one expiry's implied volatility by strike, from the
 * out-of-the-money side: puts below the forward, calls above.
 */
import { useState } from "react";

import type { ExpiryChain } from "../../lib/options-schemas";
import { niceTicks } from "../MultiLine";
import { AxisText, COLOR, Legend, PAD, Tooltip, YGrid, linear, money, pct, useChartWidth } from "./chart-kit";

const HEIGHT = 220;

export function SmileChart({ chain }: { chain: ExpiryChain }) {
  const [ref, W] = useChartWidth();
  const [hover, setHover] = useState<number | null>(null);
  const points = [...chain.smile].sort((a, b) => a.strike - b.strike);
  if (points.length < 3) return null;

  const strikes = points.map((p) => p.strike);
  const x = linear(Math.min(...strikes), Math.max(...strikes), PAD.left, W - PAD.right);
  const ticks = niceTicks(Math.min(...points.map((p) => p.iv)) * 0.95, Math.max(...points.map((p) => p.iv)) * 1.05);
  const y = linear(ticks[0], ticks[ticks.length - 1], HEIGHT - PAD.bottom, PAD.top);
  const xTicks = niceTicks(Math.min(...strikes), Math.max(...strikes), 5).filter((t) => t >= strikes[0] && t <= strikes[strikes.length - 1]);
  const path = (side: "put" | "call") =>
    points
      .filter((p) => p.side === side)
      .map((p, i) => `${i ? "L" : "M"}${x(p.strike)},${y(p.iv)}`)
      .join(" ");
  const shown = hover === null ? null : points[hover];

  return (
    <div ref={ref} className="relative w-full overflow-x-auto" data-testid="options-smile">
      <Legend items={[{ label: "Puts", color: COLOR.put }, { label: "Calls", color: COLOR.call }]} />
      <svg
        width={W}
        height={HEIGHT}
        viewBox={`0 0 ${W} ${HEIGHT}`}
        role="img"
        aria-label={`Implied volatility by strike for ${chain.expiry}, ${pct(points[0].iv)} at ${money(points[0].strike)} to ${pct(points[points.length - 1].iv)} at ${money(points[points.length - 1].strike)}.`}
        onMouseLeave={() => setHover(null)}
      >
        <YGrid ticks={ticks} y={y} x0={PAD.left} x1={W - PAD.right} format={(v) => pct(v, 0)} />
        {xTicks.map((t) => (
          <AxisText key={t} x={x(t)} y={HEIGHT - 8} anchor="middle">
            {`$${t}`}
          </AxisText>
        ))}
        <g data-testid="options-smile-forward">
          <line x1={x(chain.forward)} x2={x(chain.forward)} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke={COLOR.axis} strokeDasharray="4 3" />
          <AxisText x={x(chain.forward) + 4} y={PAD.top + 10} anchor="start">
            {`forward ${money(chain.forward)}`}
          </AxisText>
        </g>
        <path d={path("put")} fill="none" stroke={COLOR.put} strokeWidth={2} />
        <path d={path("call")} fill="none" stroke={COLOR.call} strokeWidth={2} />
        {points.map((p, i) => (
          <circle
            key={p.strike}
            data-testid="options-smile-dot"
            cx={x(p.strike)}
            cy={y(p.iv)}
            r={hover === i ? 5 : 4}
            fill={p.side === "put" ? COLOR.put : COLOR.call}
            stroke={COLOR.surface}
            strokeWidth={2}
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>
      {shown && (
        <Tooltip testId="options-smile-tooltip" left={x(shown.strike)} width={W}>
          <p className="text-strata-hi">Strike {money(shown.strike)}</p>
          <p>
            {shown.side} IV {pct(shown.iv)}
          </p>
        </Tooltip>
      )}
    </div>
  );
}
