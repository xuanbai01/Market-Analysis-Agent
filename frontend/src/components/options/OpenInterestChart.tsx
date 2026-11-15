/**
 * OpenInterestChart — one expiry's open interest by strike: calls above
 * the line, puts below, the spot marked.
 */
import { useState } from "react";

import type { ExpiryChain } from "../../lib/options-schemas";
import { niceTicks } from "../MultiLine";
import { AxisText, COLOR, Legend, PAD, Tooltip, linear, markerText, money, useChartWidth } from "./chart-kit";

const HEIGHT = 220;

const count = (v: number) => (v >= 1000 ? `${(v / 1000).toFixed(v >= 10_000 ? 0 : 1)}k` : String(v));

export function OpenInterestChart({ chain, spot }: { chain: ExpiryChain; spot: number | null }) {
  const maxPain = chain.positioning?.max_pain ?? null;
  const [ref, W] = useChartWidth();
  const [hover, setHover] = useState<number | null>(null);
  const points = [...chain.open_interest].sort((a, b) => a.strike - b.strike);
  if (points.length === 0) return null;

  const strikes = points.map((p) => p.strike);
  const low = strikes[0];
  const high = strikes[strikes.length - 1];
  const x = linear(low, high, PAD.left + 12, W - PAD.right - 12);
  const gaps = strikes.slice(1).map((s, i) => x(s) - x(strikes[i]));
  const barW = Math.max(3, Math.min(18, (gaps.length ? Math.min(...gaps) : 24) * 0.7));
  const most = Math.max(...points.map((p) => Math.max(p.call, p.put)), 1);
  const mid = (HEIGHT - PAD.bottom + PAD.top) / 2;
  const h = linear(0, most, 0, mid - PAD.top);
  const xTicks = niceTicks(low, high, 6).filter((t) => t >= low && t <= high);
  const shown = hover === null ? null : points[hover];

  return (
    <div ref={ref} className="relative w-full overflow-x-auto" data-testid="options-oi">
      <Legend items={[{ label: "Calls", color: COLOR.call }, { label: "Puts", color: COLOR.put }]} />
      <svg
        width={W}
        height={HEIGHT}
        viewBox={`0 0 ${W} ${HEIGHT}`}
        role="img"
        aria-label={`Open interest by strike for ${chain.expiry}, calls above the line and puts below.`}
        onMouseLeave={() => setHover(null)}
      >
        <line x1={PAD.left} x2={W - PAD.right} y1={mid} y2={mid} stroke={COLOR.grid} />
        <AxisText x={PAD.left - 8} y={PAD.top + 10}>{count(most)}</AxisText>
        <AxisText x={PAD.left - 8} y={HEIGHT - PAD.bottom}>{count(most)}</AxisText>
        {xTicks.map((t) => (
          <AxisText key={t} x={x(t)} y={HEIGHT - 8} anchor="middle">
            {`$${t}`}
          </AxisText>
        ))}
        {spot !== null && spot >= low && spot <= high && (
          <g data-testid="options-oi-price">
            <line x1={x(spot)} x2={x(spot)} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke={COLOR.axis} strokeDasharray="4 3" />
            <AxisText {...markerText(x(spot), W)} y={PAD.top + 10}>
              {`price ${money(spot)}`}
            </AxisText>
          </g>
        )}
        {maxPain !== null && maxPain >= low && maxPain <= high && (
          <g data-testid="options-oi-max-pain">
            <line x1={x(maxPain)} x2={x(maxPain)} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke={COLOR.neutral} strokeDasharray="1 3" />
            <AxisText {...markerText(x(maxPain), W)} y={PAD.top + 22}>
              {`max pain ${money(maxPain)}`}
            </AxisText>
          </g>
        )}
        {points.map((p, i) => (
          <g key={p.strike} opacity={hover === null || hover === i ? 1 : 0.5}>
            {p.call > 0 && (
              <rect data-testid="options-oi-call" x={x(p.strike) - barW / 2} y={mid - h(p.call) - 1} width={barW} height={h(p.call)} rx={2} fill={COLOR.call} />
            )}
            {p.put > 0 && (
              <rect data-testid="options-oi-put" x={x(p.strike) - barW / 2} y={mid + 1} width={barW} height={h(p.put)} rx={2} fill={COLOR.put} />
            )}
            <rect
              data-testid="options-oi-hit"
              x={x(p.strike) - Math.max(barW, 10) / 2}
              y={PAD.top}
              width={Math.max(barW, 10)}
              height={HEIGHT - PAD.top - PAD.bottom}
              fill="transparent"
              onMouseEnter={() => setHover(i)}
            />
          </g>
        ))}
      </svg>
      {shown && (
        <Tooltip testId="options-oi-tooltip" left={x(shown.strike)} width={W}>
          <p className="text-strata-hi">Strike {money(shown.strike)}</p>
          <p>Calls {shown.call.toLocaleString("en-US")}</p>
          <p>Puts {shown.put.toLocaleString("en-US")}</p>
        </Tooltip>
      )}
    </div>
  );
}
