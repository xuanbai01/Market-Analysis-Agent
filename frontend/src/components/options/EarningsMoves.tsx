/**
 * EarningsMoves — the move the options price through the next report,
 * against the moves the last reports made (signed bars). The implied move
 * is a band at ±its size; when it's refused, the reason is said instead.
 */
import { useState } from "react";

import type { EarningsBlock, Timing } from "../../lib/options-schemas";
import { AxisText, COLOR, PAD, Tooltip, linear, money, pct, shortDate, useChartWidth } from "./chart-kit";

const HEIGHT = 200;

const TIMING: Record<Timing, string> = {
  before_open: "before the open",
  during: "during the session",
  after_close: "after the close",
  unknown: "time not given",
};

export function EarningsMoves({ earnings }: { earnings: EarningsBlock }) {
  const [ref, W] = useChartWidth();
  const [hover, setHover] = useState<number | null>(null);
  const { past, implied_move: implied } = earnings;
  if (past.length === 0 && implied === null && earnings.next_date === null) return null;

  const most = Math.max(...past.map((m) => Math.abs(m.move)), implied ?? 0, 0.01) * 1.15;
  const y = linear(-most, most, HEIGHT - PAD.bottom, PAD.top);
  const band = (W - PAD.left - PAD.right) / Math.max(past.length, 1);
  const barW = Math.min(28, band * 0.55);
  const cx = (i: number) => PAD.left + band * (i + 0.5);
  const shown = hover === null ? null : past[hover];

  return (
    <div ref={ref} className="relative w-full overflow-x-auto" data-testid="options-earnings">
      <p data-testid="options-earnings-summary" className="mb-3 text-sm text-strata-dim">
        {earnings.next_date && (
          <>
            Next report {shortDate(earnings.next_date, true)}
            {earnings.next_timing ? `, ${TIMING[earnings.next_timing]}` : ""}
            {earnings.estimated ? " (estimated)" : ""}.{" "}
          </>
        )}
        {implied !== null ? (
          <>
            Options price a move of <span className="text-strata-hi">±{pct(implied)}</span>
            {earnings.implied_move_usd !== null && <> ({money(earnings.implied_move_usd)})</>} through it.{" "}
          </>
        ) : (
          earnings.refused && <>No implied move: {earnings.refused}. </>
        )}
        {past.length > 0 && earnings.past_mean_abs !== null && (
          <>
            The last {past.length} reports moved <span className="text-strata-hi">{pct(earnings.past_mean_abs)}</span> on
            average.
          </>
        )}
      </p>
      {past.length > 0 && (
        <svg
          width={W}
          height={HEIGHT}
          viewBox={`0 0 ${W} ${HEIGHT}`}
          role="img"
          aria-label={`Moves after the last ${past.length} reports${implied !== null ? `, against ±${pct(implied)} priced for the next` : ""}.`}
          onMouseLeave={() => setHover(null)}
        >
          {implied !== null && (
            <g data-testid="options-earnings-band">
              <rect x={PAD.left} y={y(implied)} width={W - PAD.left - PAD.right} height={y(-implied) - y(implied)} fill={COLOR.band} fillOpacity={0.14} />
              <AxisText x={W - PAD.right} y={y(implied) - 4}>{`±${pct(implied)} priced`}</AxisText>
            </g>
          )}
          <line x1={PAD.left} x2={W - PAD.right} y1={y(0)} y2={y(0)} stroke={COLOR.grid} />
          {[most, -most].map((t) => (
            <AxisText key={t} x={PAD.left - 8} y={y(t) + 4}>{`${t > 0 ? "+" : ""}${pct(t, 0)}`}</AxisText>
          ))}
          {past.map((m, i) => (
            <g key={m.announced} opacity={hover === null || hover === i ? 1 : 0.5}>
              <rect
                data-testid="options-earnings-bar"
                x={cx(i) - barW / 2}
                y={Math.min(y(0), y(m.move))}
                width={barW}
                height={Math.max(1, Math.abs(y(m.move) - y(0)))}
                rx={2}
                fill={COLOR.neutral}
              />
              <AxisText x={cx(i)} y={HEIGHT - 8} anchor="middle">
                {shortDate(m.announced).split(" ")[0] + ` '${m.announced.slice(2, 4)}`}
              </AxisText>
              <rect x={cx(i) - band / 2} y={PAD.top} width={band} height={HEIGHT - PAD.top - PAD.bottom} fill="transparent" onMouseEnter={() => setHover(i)} />
            </g>
          ))}
        </svg>
      )}
      {shown && hover !== null && (
        <Tooltip testId="options-earnings-tooltip" left={cx(hover)} width={W}>
          <p className="text-strata-hi">{shortDate(shown.announced, true)}</p>
          <p className="text-strata-dim">{TIMING[shown.timing]}</p>
          <p>
            {shown.move > 0 ? "+" : ""}
            {pct(shown.move)}
            {shown.spans_extra_day ? " (two sessions)" : ""}
          </p>
        </Tooltip>
      )}
    </div>
  );
}
