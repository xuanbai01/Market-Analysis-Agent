/**
 * ExposureChart — one expiry's net gamma or delta exposure by strike, in
 * dollars per 1% move: a bar up where calls dominate (the calls' blue),
 * down where puts do (the puts' orange), the price and, for gamma, the
 * flip marked. The walls go in the stats table under it, and the dealer
 * assumption is the caller's to state beside it.
 */
import { useState } from "react";

import type { Positioning } from "../../lib/options-schemas";
import { compactUsd, strikeLabel } from "../../lib/options-text";
import { niceTicks } from "../MultiLine";
import { AxisText, COLOR, PAD, Tooltip, YGrid, linear, money, useChartWidth } from "./chart-kit";

const HEIGHT = 220;

interface Props {
  positioning: Positioning;
  field: "gex" | "dex";
  price: number | null;
  testId: string;
}

export function ExposureChart({ positioning, field, price, testId }: Props) {
  const [ref, W] = useChartWidth();
  const [hover, setHover] = useState<number | null>(null);
  const points = [...positioning.exposure].sort((a, b) => a.strike - b.strike).filter((p) => p[field] !== 0);
  if (points.length === 0) return null;

  const strikes = points.map((p) => p.strike);
  const low = strikes[0];
  const high = strikes[strikes.length - 1];
  const x = linear(low, high, PAD.left + 12, W - PAD.right - 12);
  const gaps = strikes.slice(1).map((s, i) => x(s) - x(strikes[i]));
  const barW = Math.max(3, Math.min(16, (gaps.length ? Math.min(...gaps) : 24) * 0.7));
  const values = points.map((p) => p[field]);
  const ticks = niceTicks(Math.min(0, ...values), Math.max(0, ...values), 4);
  const y = linear(ticks[0], ticks[ticks.length - 1], HEIGHT - PAD.bottom, PAD.top);
  const xTicks = niceTicks(low, high, 6).filter((t) => t >= low && t <= high);
  const marks: { at: number; label: string; id: string }[] = [];
  if (price !== null && price >= low && price <= high) marks.push({ at: price, label: `price ${money(price)}`, id: "price" });
  if (field === "gex" && positioning.gamma_flip !== null && positioning.gamma_flip >= low && positioning.gamma_flip <= high) {
    marks.push({ at: positioning.gamma_flip, label: `flip ${money(positioning.gamma_flip)}`, id: "flip" });
  }
  const shown = hover === null ? null : points[hover];
  const what = field === "gex" ? "gamma" : "delta";

  return (
    <div ref={ref} className="relative w-full overflow-x-auto" data-testid={testId}>
      <svg
        width={W}
        height={HEIGHT}
        viewBox={`0 0 ${W} ${HEIGHT}`}
        role="img"
        aria-label={`Net ${what} exposure by strike, dollars per 1% move: ${compactUsd(field === "gex" ? positioning.net_gex : positioning.net_dex)} in all.`}
        onMouseLeave={() => setHover(null)}
      >
        <YGrid ticks={ticks} y={y} x0={PAD.left} x1={W - PAD.right} format={(v) => compactUsd(v)} />
        <line x1={PAD.left} x2={W - PAD.right} y1={y(0)} y2={y(0)} stroke={COLOR.axis} strokeWidth={1} />
        {xTicks.map((t) => (
          <AxisText key={t} x={x(t)} y={HEIGHT - 8} anchor="middle">
            {`$${t}`}
          </AxisText>
        ))}
        {marks.map((m, i) => (
          <g key={m.id} data-testid={`${testId}-${m.id}`}>
            <line
              x1={x(m.at)}
              x2={x(m.at)}
              y1={PAD.top}
              y2={HEIGHT - PAD.bottom}
              stroke={COLOR.axis}
              strokeDasharray={m.id === "flip" ? "1 3" : "4 3"}
            />
            <AxisText x={x(m.at) + 4} y={PAD.top + 10 + i * 12} anchor="start">
              {m.label}
            </AxisText>
          </g>
        ))}
        {points.map((p, i) => {
          const v = p[field];
          return (
            <rect
              key={p.strike}
              data-testid={`${testId}-bar`}
              x={x(p.strike) - barW / 2}
              y={v >= 0 ? y(v) : y(0)}
              width={barW}
              height={Math.max(1, Math.abs(y(v) - y(0)))}
              rx={2}
              fill={v >= 0 ? COLOR.call : COLOR.put}
              opacity={hover === null || hover === i ? 1 : 0.5}
            />
          );
        })}
        {points.map((p, i) => (
          <rect
            key={`hit-${p.strike}`}
            data-testid={`${testId}-hit`}
            x={x(p.strike) - Math.max(barW, 10) / 2}
            y={PAD.top}
            width={Math.max(barW, 10)}
            height={HEIGHT - PAD.top - PAD.bottom}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>
      {shown && (
        <Tooltip testId={`${testId}-tooltip`} left={x(shown.strike)} width={W}>
          <p className="text-strata-hi">Strike {strikeLabel(shown.strike)}</p>
          <p>
            Net {what} {compactUsd(shown[field])} per 1% move
          </p>
        </Tooltip>
      )}
    </div>
  );
}
