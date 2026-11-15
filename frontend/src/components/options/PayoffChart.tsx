/**
 * PayoffChart — profit or loss per contract at expiry against the stock's
 * price then: at mid (solid) and at the natural price (dashed, the same
 * shape lower by the extra cost of crossing the spread); either can be
 * missing, not both. The shaded band is the expiry's one-sigma range
 * around the forward, when there's an IV to draw it from; dots on the
 * zero line are the breakevens.
 */
import { useState } from "react";

import type { Analysis, PricedLeg } from "../../lib/options-strategy";
import { CONTRACT_SIZE, payoff } from "../../lib/options-strategy";
import { niceTicks } from "../MultiLine";
import { AxisText, COLOR, Legend, PAD, Tooltip, YGrid, hitBands, linear, money, useChartWidth } from "./chart-kit";

const HEIGHT = 240;
const HOVER_STOPS = 60;

interface Props {
  mid: Analysis | null;
  natural: Analysis | null;
  forward: number;
  /** The expiry's one-sigma move, σ√T; null without an IV. */
  sigma: number | null;
}

// Without a sigma, the range runs this far past the strikes and forward.
const RANGE_PAD = 0.15;

const perContract = (legs: PricedLeg[], price: number) => payoff(legs, price) * CONTRACT_SIZE;

function dollars(v: number): string {
  const sign = v < 0 ? "−" : v > 0 ? "+" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function PayoffChart({ mid, natural, forward, sigma }: Props) {
  const [ref, W] = useChartWidth();
  const [hover, setHover] = useState<number | null>(null);
  const main = mid ?? natural;
  if (!main) return null;

  const strikes = main.priced.map((l) => l.strike);
  const band = sigma !== null && sigma > 0 ? { lo: forward * Math.exp(-sigma), hi: forward * Math.exp(sigma) } : null;
  const reach = band ? [forward * Math.exp(-2 * (sigma ?? 0)), forward * Math.exp(2 * (sigma ?? 0))] : [forward * (1 - RANGE_PAD), forward * (1 + RANGE_PAD)];
  const lo = Math.min(...strikes, reach[0]) * 0.97;
  const hi = Math.max(...strikes, reach[1]) * 1.03;
  // The payoff bends only at strikes, so the ends and the strikes draw it exactly.
  const xsDrawn = [lo, ...strikes.filter((k) => k > lo && k < hi).sort((a, b) => a - b), hi];
  const series = [mid, natural].filter((s): s is Analysis => s !== null);
  const values = series.flatMap((s) => xsDrawn.map((p) => perContract(s.priced, p)));
  const ticks = niceTicks(Math.min(0, ...values), Math.max(0, ...values));
  const x = linear(lo, hi, PAD.left, W - PAD.right);
  const y = linear(ticks[0], ticks[ticks.length - 1], HEIGHT - PAD.bottom, PAD.top);
  const path = (legs: PricedLeg[]) => xsDrawn.map((p, i) => `${i ? "L" : "M"}${x(p)},${y(perContract(legs, p))}`).join(" ");
  const xTicks = niceTicks(lo, hi, 5).filter((t) => t >= lo && t <= hi);
  const stops = Array.from({ length: HOVER_STOPS }, (_, i) => lo + ((hi - lo) * (i + 0.5)) / HOVER_STOPS);
  const bands = hitBands(stops.map(x), PAD.left, W - PAD.right);
  const shownPrice = hover === null ? null : stops[hover];

  return (
    <div ref={ref} className="relative w-full overflow-x-auto" data-testid="strategy-payoff">
      <Legend
        items={[
          ...(mid ? [{ label: "At mid", color: COLOR.hi }] : []),
          ...(natural ? [{ label: "At the natural price (dashed)", color: COLOR.neutral }] : []),
        ]}
      />
      <svg
        width={W}
        height={HEIGHT}
        viewBox={`0 0 ${W} ${HEIGHT}`}
        role="img"
        aria-label={`Profit or loss per contract at expiry, from ${dollars(Math.min(...values))} to ${dollars(Math.max(...values))} for prices from ${money(lo)} to ${money(hi)}${main.breakevens.length ? `; breakeven at ${main.breakevens.map(money).join(" and ")}` : ""}.`}
        onMouseLeave={() => setHover(null)}
      >
        {band && (
          <g data-testid="strategy-payoff-band">
            <rect x={x(band.lo)} y={PAD.top} width={x(band.hi) - x(band.lo)} height={HEIGHT - PAD.top - PAD.bottom} fill={COLOR.band} fillOpacity={0.08} />
            <AxisText x={x(band.hi) - 4} y={PAD.top + 12} anchor="end">±1σ</AxisText>
          </g>
        )}
        <YGrid ticks={ticks} y={y} x0={PAD.left} x1={W - PAD.right} format={dollars} />
        <line x1={PAD.left} x2={W - PAD.right} y1={y(0)} y2={y(0)} stroke={COLOR.axis} strokeWidth={1} />
        {xTicks.map((t) => (
          <AxisText key={t} x={x(t)} y={HEIGHT - 8} anchor="middle">{`$${Math.round(t)}`}</AxisText>
        ))}
        {natural && (
          <path data-testid="strategy-payoff-natural" d={path(natural.priced)} fill="none" stroke={COLOR.neutral} strokeWidth={1.5} strokeDasharray="5 4" />
        )}
        {mid && <path data-testid="strategy-payoff-mid" d={path(mid.priced)} fill="none" stroke={COLOR.hi} strokeWidth={2} />}
        {main.breakevens
          .filter((b) => b >= lo && b <= hi)
          .map((b) => (
            <circle key={b} cx={x(b)} cy={y(0)} r={4} fill={COLOR.surface} stroke={COLOR.hi} strokeWidth={2} />
          ))}
        {shownPrice !== null && (
          <line x1={x(shownPrice)} x2={x(shownPrice)} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke={COLOR.axis} strokeWidth={1} />
        )}
        {bands.map(({ left, width }, i) => (
          <rect
            key={i}
            data-testid="strategy-payoff-hit"
            x={left}
            y={PAD.top}
            width={width}
            height={HEIGHT - PAD.top - PAD.bottom}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>
      {shownPrice !== null && (
        <Tooltip testId="strategy-payoff-tooltip" left={x(shownPrice)} width={W}>
          <p className="text-strata-hi">Stock at {money(shownPrice)} at expiry</p>
          {mid && <p>{dollars(perContract(mid.priced, shownPrice))} at mid</p>}
          {natural && <p className="text-strata-dim">{dollars(perContract(natural.priced, shownPrice))} at the natural price</p>}
        </Tooltip>
      )}
    </div>
  );
}
