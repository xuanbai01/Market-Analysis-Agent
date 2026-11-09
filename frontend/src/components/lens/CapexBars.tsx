/**
 * CapexBars — the lens's capex in dollars: one stacked bar per year, one
 * segment per company (lens colors, fixed order bottom-up), the total on
 * top. Shows scale and concentration that intensity alone hides.
 * Hovering a year lists each company's spend, largest first.
 */
import { useState } from "react";

import { companiesInYear, companyColor, usdBillions } from "../../lib/lens";
import type { LensReport } from "../../lib/schemas";
import { useMeasuredWidth } from "../../lib/use-measured-width";
import { niceTicks } from "../MultiLine";

interface Props {
  report: Pick<LensReport, "years" | "companies">;
  height?: number;
}

const FALLBACK_WIDTH = 640;
// Below this the scales would invert (negative inner width); the chart
// keeps this width and scrolls sideways instead.
const MIN_WIDTH = 360;
const PAD = { top: 18, right: 12, bottom: 26, left: 50 };
const SURFACE = "#0e1116";

export function CapexBars({ report, height = 240 }: Props) {
  const [measureRef, measured] = useMeasuredWidth();
  const [hover, setHover] = useState<number | null>(null);
  const { years, companies } = report;
  if (years.length === 0) return null;

  const totals = years.map((_, i) => companies.reduce((sum, c) => sum + (c.points[i]?.capex ?? 0), 0));
  const ticks = niceTicks(0, Math.max(...totals), 4);
  const yMax = ticks[ticks.length - 1] || 1;
  const W = Math.max(MIN_WIDTH, measured ?? FALLBACK_WIDTH);
  const innerW = W - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;
  const band = innerW / years.length;
  const barW = Math.max(6, band * 0.62);
  const xCenter = (i: number) => PAD.left + band * (i + 0.5);
  const y = (v: number) => PAD.top + (1 - v / yMax) * innerH;
  const showTotals = band >= 38;

  return (
    <div ref={measureRef} className="relative w-full overflow-x-auto" data-testid="lens-bars">
      <svg
        width={W}
        height={height}
        viewBox={`0 0 ${W} ${height}`}
        role="img"
        aria-label={`Total capex by year, ${usdBillions(totals[0])} in CY${years[0]} to ${usdBillions(totals[totals.length - 1])} in CY${years[years.length - 1]}.`}
        onMouseLeave={() => setHover(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke="#1f2630" strokeWidth={1} />
            <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="#8892a0" fontFamily="JetBrains Mono, monospace">
              {t === 0 ? "$0" : `$${Math.round(t / 1e9)}B`}
            </text>
          </g>
        ))}
        {years.map((year, i) => {
          let base = 0;
          return (
            <g key={year}>
              {companies.map((c, index) => {
                const v = c.points[i]?.capex ?? 0;
                if (v <= 0) return null;
                const top = y(base + v);
                const h = y(base) - top;
                base += v;
                return (
                  <rect
                    key={c.ticker}
                    data-testid="lens-segment"
                    data-ticker={c.ticker}
                    data-year={year}
                    x={xCenter(i) - barW / 2}
                    y={top}
                    width={barW}
                    height={Math.max(0, h)}
                    fill={companyColor(index)}
                    fillOpacity={hover === null || hover === i ? 1 : 0.45}
                    stroke={SURFACE}
                    strokeWidth={1}
                  />
                );
              })}
              {showTotals && (
                <text
                  data-testid="lens-bar-total"
                  x={xCenter(i)}
                  y={y(totals[i]) - 5}
                  textAnchor="middle"
                  fontSize={10}
                  fill="#8892a0"
                  fontFamily="JetBrains Mono, monospace"
                >
                  {`$${Math.round(totals[i] / 1e9)}B`}
                </text>
              )}
              <text x={xCenter(i)} y={height - 8} textAnchor="middle" fontSize={11} fill="#8892a0" fontFamily="JetBrains Mono, monospace">
                {`'${String(year).slice(2)}`}
              </text>
              <rect
                data-testid="lens-bar-column"
                x={xCenter(i) - band / 2}
                y={PAD.top}
                width={band}
                height={innerH}
                fill="transparent"
                onMouseEnter={() => setHover(i)}
              />
            </g>
          );
        })}
      </svg>

      {hover !== null && (
        <div
          data-testid="lens-bars-tooltip"
          className="pointer-events-none absolute top-2 z-10 w-44 rounded-md border border-strata-border bg-strata-surface/95 p-2.5 font-mono text-[11px] shadow-lg"
          style={{ left: Math.min(Math.max(0, xCenter(hover) + barW), W - 184) }}
        >
          <p className="mb-1 flex justify-between text-strata-hi">
            <span>CY{years[hover]}</span>
            <span>{usdBillions(totals[hover])}</span>
          </p>
          <ul className="space-y-0.5">
            {companiesInYear(report, years[hover])
              .filter((r) => r.capex !== null)
              .sort((a, b) => (b.capex ?? 0) - (a.capex ?? 0))
              .map((row) => (
                <li key={row.ticker} className="flex items-center justify-between gap-2">
                  <span className="flex items-center gap-1.5 text-strata-dim">
                    <span className="h-2 w-2 rounded-full" style={{ background: row.color }} aria-hidden="true" />
                    {row.ticker}
                  </span>
                  <span className="text-strata-fg">{usdBillions(row.capex ?? 0)}</span>
                </li>
              ))}
          </ul>
        </div>
      )}
    </div>
  );
}
