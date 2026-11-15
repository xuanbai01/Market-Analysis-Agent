/**
 * PositionPayoffChart — a position's profit or loss against the stock's
 * price: at its first expiry (solid; legs expiring later valued then), and
 * in the what-if (dashed: today at today's IVs until the controls move).
 * The shaded band is the first expiry's one-sigma range; the vertical line
 * is the price now; dots on the zero line are the breakevens at expiry.
 */
import { useState } from "react";

import { dateLabel } from "../../lib/options-text";
import type { PositionGroup } from "../../lib/owner-schemas";
import { type Market, type Scenario, breakevens, firstExpiry, pnlAtExpiry, pnlInScenario } from "../../lib/positions-math";
import { signedUsd } from "../../lib/positions-text";
import { niceTicks } from "../MultiLine";
import { AxisText, COLOR, Legend, PAD, Tooltip, YGrid, hitBands, linear, markerText, money, useChartWidth } from "../options/chart-kit";

const HEIGHT = 260;
const SAMPLES = 120;
const HOVER_STOPS = 60;
// With no IV to size it, the range runs this far either side of the price.
const MIN_SPREAD = 0.1;
const SIGMAS_SHOWN = 2.5;

interface Props {
  group: PositionGroup;
  market: Market;
  scenario: Scenario;
  /** The first expiry's one-sigma move, σ√T; null without an IV. */
  sigma: number | null;
}

function path(xs: number[], ys: (number | null)[], x: (v: number) => number, y: (v: number) => number): string | null {
  if (ys.some((v) => v === null)) return null;
  return xs.map((p, i) => `${i ? "L" : "M"}${x(p)},${y(ys[i] as number)}`).join(" ");
}

export function PositionPayoffChart({ group, market, scenario, sigma }: Props) {
  const [ref, W] = useChartWidth();
  const [hover, setHover] = useState<number | null>(null);
  const { spot } = market;
  const expiry = firstExpiry(group);
  const spread = Math.max(sigma ?? 0, MIN_SPREAD);
  const strikes = group.legs.flatMap((l) => (l.strike === null ? [] : [l.strike]));
  const lo = Math.min(spot * Math.exp(-SIGMAS_SHOWN * spread), ...strikes.map((k) => k * 0.97));
  const hi = Math.max(spot * Math.exp(SIGMAS_SHOWN * spread), ...strikes.map((k) => k * 1.03));
  const xs = Array.from({ length: SAMPLES + 1 }, (_, i) => lo + ((hi - lo) * i) / SAMPLES);
  const whatIf = (price: number) => pnlInScenario(group, { ...scenario, move: price / spot - 1 }, market);
  const atExpiry = expiry ? xs.map((p) => pnlAtExpiry(group, p, market)) : xs.map(() => null);
  const inScenario = xs.map(whatIf);
  const drawnExpiry = atExpiry.every((v) => v !== null);
  const drawnScenario = inScenario.every((v) => v !== null);
  if (!drawnExpiry && !drawnScenario) return null;

  const values = [...(drawnExpiry ? atExpiry : []), ...(drawnScenario ? inScenario : [])] as number[];
  const ticks = niceTicks(Math.min(0, ...values), Math.max(0, ...values));
  const x = linear(lo, hi, PAD.left, W - PAD.right);
  const y = linear(ticks[0], ticks[ticks.length - 1], HEIGHT - PAD.bottom, PAD.top);
  const expiryPath = drawnExpiry ? path(xs, atExpiry, x, y) : null;
  const scenarioPath = drawnScenario ? path(xs, inScenario, x, y) : null;
  const evens = drawnExpiry ? breakevens(group, market).filter((b) => b >= lo && b <= hi) : [];
  const band = sigma !== null && sigma > 0 ? { lo: spot * Math.exp(-sigma), hi: spot * Math.exp(sigma) } : null;
  const scenarioPrice = spot * (1 + scenario.move);
  const scenarioPnl = drawnScenario ? whatIf(scenarioPrice) : null;
  const moved = scenario.move !== 0 || scenario.ivShift !== 0 || scenario.days !== 0;
  const scenarioLabel = moved ? "What-if (dashed)" : "Today, at today's IVs (dashed)";
  const xTicks = niceTicks(lo, hi, 5).filter((t) => t >= lo && t <= hi);
  const stops = Array.from({ length: HOVER_STOPS }, (_, i) => lo + ((hi - lo) * (i + 0.5)) / HOVER_STOPS);
  const bands = hitBands(stops.map(x), PAD.left, W - PAD.right);
  const shown = hover === null ? null : stops[hover];
  const now = markerText(x(spot), W);

  return (
    // overflow-x-auto: below the chart's minimum width it scrolls inside its card.
    <div ref={ref} className="relative w-full overflow-x-auto" data-testid="position-payoff">
      <Legend
        items={[
          ...(expiryPath && expiry ? [{ label: `At ${dateLabel(expiry)}'s close`, color: COLOR.hi }] : []),
          ...(scenarioPath ? [{ label: scenarioLabel, color: COLOR.band }] : []),
        ]}
      />
      <svg
        width={W}
        height={HEIGHT}
        viewBox={`0 0 ${W} ${HEIGHT}`}
        role="img"
        aria-label={`Profit or loss against ${group.underlying}'s price, from ${money(lo)} to ${money(hi)}${evens.length ? `; breakeven at expiry ${evens.map(money).join(" and ")}` : ""}.`}
        onMouseLeave={() => setHover(null)}
      >
        {band && (
          <g data-testid="position-payoff-band">
            <rect x={x(band.lo)} y={PAD.top} width={x(band.hi) - x(band.lo)} height={HEIGHT - PAD.top - PAD.bottom} fill={COLOR.band} fillOpacity={0.08} />
            <AxisText x={x(band.hi) - 4} y={PAD.top + 12} anchor="end">±1σ</AxisText>
          </g>
        )}
        <YGrid ticks={ticks} y={y} x0={PAD.left} x1={W - PAD.right} format={signedUsd} />
        <line x1={PAD.left} x2={W - PAD.right} y1={y(0)} y2={y(0)} stroke={COLOR.axis} strokeWidth={1} />
        {xTicks.map((t) => (
          <AxisText key={t} x={x(t)} y={HEIGHT - 8} anchor="middle">{`$${Math.round(t)}`}</AxisText>
        ))}
        <line data-testid="position-payoff-now" x1={x(spot)} x2={x(spot)} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke={COLOR.neutral} strokeWidth={1} strokeDasharray="2 3" />
        <AxisText x={now.x} y={PAD.top + 24} anchor={now.anchor}>{`Now ${money(spot)}`}</AxisText>
        {scenarioPath && <path data-testid="position-payoff-scenario" d={scenarioPath} fill="none" stroke={COLOR.band} strokeWidth={1.5} strokeDasharray="5 4" />}
        {expiryPath && <path data-testid="position-payoff-expiry" d={expiryPath} fill="none" stroke={COLOR.hi} strokeWidth={2} />}
        {evens.map((b) => (
          <circle key={b} cx={x(b)} cy={y(0)} r={4} fill={COLOR.surface} stroke={COLOR.hi} strokeWidth={2} />
        ))}
        {moved && scenarioPnl !== null && scenarioPrice >= lo && scenarioPrice <= hi && (
          <circle data-testid="position-payoff-scenario-point" cx={x(scenarioPrice)} cy={y(scenarioPnl)} r={5} fill={COLOR.band} stroke={COLOR.surface} strokeWidth={2} />
        )}
        {shown !== null && <line x1={x(shown)} x2={x(shown)} y1={PAD.top} y2={HEIGHT - PAD.bottom} stroke={COLOR.axis} strokeWidth={1} />}
        {bands.map(({ left, width }, i) => (
          <rect key={i} x={left} y={PAD.top} width={width} height={HEIGHT - PAD.top - PAD.bottom} fill="transparent" onMouseEnter={() => setHover(i)} />
        ))}
      </svg>
      {shown !== null && (
        <Tooltip testId="position-payoff-tooltip" left={x(shown)} width={W}>
          <p className="text-strata-hi">{group.underlying} at {money(shown)}</p>
          {expiryPath && expiry && <p>{signedUsd(pnlAtExpiry(group, shown, market) ?? 0)} at {dateLabel(expiry)}&rsquo;s close</p>}
          {scenarioPath && <p className="text-strata-dim">{signedUsd(whatIf(shown) ?? 0)} {moved ? "in the what-if" : "today"}</p>}
        </Tooltip>
      )}
    </div>
  );
}
