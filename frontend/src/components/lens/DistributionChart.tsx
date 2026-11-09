/**
 * DistributionChart — how capex intensity is spread across the lens's
 * companies, year by year.
 *
 *   shaded band   the middle 50% (25th–75th percentile) of the group
 *   white line    the group median
 *   dots          each company, in its lens color, joined by a faint
 *                 trajectory; tickers label the latest year directly
 *
 * One y-axis (percent of revenue) from a 0% baseline. Hovering a year
 * shows every company's value, ranked, with the median and band.
 */
import { useState } from "react";

import { companiesInYear, companyColor, pct } from "../../lib/lens";
import type { LensReport } from "../../lib/schemas";
import { useMeasuredWidth } from "../../lib/use-measured-width";
import { niceTicks } from "../MultiLine";

interface Props {
  report: Pick<LensReport, "years" | "companies" | "stats">;
  height?: number;
}

const FALLBACK_WIDTH = 640;
// Below this the scales would invert (negative inner width); the chart
// keeps this width and scrolls sideways instead.
const MIN_WIDTH = 360;
const PAD = { top: 14, right: 64, bottom: 26, left: 42 };
const LABEL_GAP = 12;
const SURFACE = "#0e1116";
const MEDIAN = "#f5f7fb";

export function DistributionChart({ report, height = 300 }: Props) {
  const [measureRef, measured] = useMeasuredWidth();
  const [hover, setHover] = useState<number | null>(null);
  const { years, companies, stats } = report;
  if (years.length < 2 || stats.length === 0) return null;

  const W = Math.max(MIN_WIDTH, measured ?? FALLBACK_WIDTH);
  const innerW = W - PAD.left - PAD.right;
  const innerH = height - PAD.top - PAD.bottom;
  const values = companies.flatMap((c) => c.points.map((p) => p.capex_intensity ?? 0));
  const ticks = niceTicks(0, Math.max(...values, ...stats.map((s) => s.p75)), 5);
  const yMax = ticks[ticks.length - 1] || 1;
  const step = innerW / (years.length - 1);
  const x = (i: number) => PAD.left + i * step;
  const y = (v: number) => PAD.top + (1 - v / yMax) * innerH;
  const yearIndex = new Map(years.map((year, i) => [year, i]));

  const statPoints = stats.map((s) => ({ ...s, i: yearIndex.get(s.year) ?? 0 }));
  const band =
    statPoints.map((s, k) => `${k ? "L" : "M"}${x(s.i)},${y(s.p75)}`).join(" ") +
    " " +
    [...statPoints].reverse().map((s) => `L${x(s.i)},${y(s.p25)}`).join(" ") +
    " Z";
  const medianPath = statPoints.map((s, k) => `${k ? "L" : "M"}${x(s.i)},${y(s.median)}`).join(" ");

  // Direct labels for the latest year, nudged apart top to bottom.
  const last = years.length - 1;
  const labels = companies
    .map((c, index) => ({ ticker: c.ticker, color: companyColor(index), v: c.points[last]?.capex_intensity }))
    .filter((l): l is { ticker: string; color: string; v: number } => l.v !== null && l.v !== undefined)
    .map((l) => ({ ...l, y: y(l.v) }))
    .sort((a, b) => a.y - b.y);
  for (let i = 1; i < labels.length; i++) {
    labels[i].y = Math.max(labels[i].y, labels[i - 1].y + LABEL_GAP);
  }

  const everyOther = step < 34;
  const first = stats[0];
  const latest = stats[stats.length - 1];
  const hoverYear = hover === null ? null : years[hover];
  const hoverStats = hoverYear === null ? null : stats.find((s) => s.year === hoverYear) ?? null;

  return (
    <div ref={measureRef} className="relative w-full overflow-x-auto" data-testid="lens-distribution">
      <svg
        width={W}
        height={height}
        viewBox={`0 0 ${W} ${height}`}
        role="img"
        aria-label={`Capex intensity by company, CY${years[0]}–CY${years[last]}. Median ${pct(first.median)} in CY${first.year}, ${pct(latest.median)} in CY${latest.year}.`}
        onMouseLeave={() => setHover(null)}
      >
        {ticks.map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} stroke="#1f2630" strokeWidth={1} />
            <text x={PAD.left - 8} y={y(t) + 4} textAnchor="end" fontSize={11} fill="#8892a0" fontFamily="JetBrains Mono, monospace">
              {`${Math.round(t * 100)}%`}
            </text>
          </g>
        ))}
        {years.map((year, i) =>
          everyOther && i % 2 === 1 && i !== last ? null : (
            <text key={year} x={x(i)} y={height - 8} textAnchor="middle" fontSize={11} fill="#8892a0" fontFamily="JetBrains Mono, monospace">
              {`'${String(year).slice(2)}`}
            </text>
          ),
        )}

        <path data-testid="lens-iqr" d={band} fill="#7e9ad4" fillOpacity={0.14} stroke="none" />
        {hover !== null && (
          <line x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + innerH} stroke="#5a6473" strokeWidth={1} />
        )}

        {companies.map((c, index) => {
          const color = companyColor(index);
          let pen = "M";
          const d = c.points
            .map((p, i) => {
              if (p.capex_intensity === null) {
                pen = "M";
                return "";
              }
              const seg = `${pen}${x(i)},${y(p.capex_intensity)}`;
              pen = "L";
              return seg;
            })
            .join(" ");
          return (
            <g key={c.ticker}>
              <path d={d} fill="none" stroke={color} strokeOpacity={0.35} strokeWidth={1.25} />
              {c.points.map((p, i) =>
                p.capex_intensity === null ? null : (
                  <circle
                    key={i}
                    data-testid="lens-dot"
                    data-ticker={c.ticker}
                    data-year={years[i]}
                    cx={x(i)}
                    cy={y(p.capex_intensity)}
                    r={hover === i ? 4.5 : 3.5}
                    fill={color}
                    stroke={SURFACE}
                    strokeWidth={1.5}
                  />
                ),
              )}
            </g>
          );
        })}

        <path data-testid="lens-median" d={medianPath} fill="none" stroke={MEDIAN} strokeWidth={1.75} />
        {statPoints.map((s) => (
          <circle key={s.year} cx={x(s.i)} cy={y(s.median)} r={2.5} fill={MEDIAN} />
        ))}

        {labels.map((l) => (
          <g key={l.ticker} data-testid="lens-end-label">
            <circle cx={W - PAD.right + 10} cy={l.y} r={3} fill={l.color} />
            <text x={W - PAD.right + 17} y={l.y + 4} fontSize={11} fill="#e6e9ef" fontFamily="JetBrains Mono, monospace">
              {l.ticker}
            </text>
          </g>
        ))}

        {years.map((year, i) => (
          <rect
            key={year}
            data-testid="lens-column"
            x={x(i) - step / 2}
            y={PAD.top}
            width={step}
            height={innerH}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>

      {hover !== null && (
        <div
          data-testid="lens-tooltip"
          className="pointer-events-none absolute top-2 z-10 w-48 rounded-md border border-strata-border bg-strata-surface/95 p-2.5 font-mono text-[11px] shadow-lg"
          style={{ left: Math.min(Math.max(0, x(hover) + 12), W - 200) }}
        >
          <p className="mb-1 text-strata-hi">CY{hoverYear}</p>
          {hoverStats && (
            <p className="mb-1.5 text-strata-muted">
              median {pct(hoverStats.median)} · middle 50% {pct(hoverStats.p25)}–{pct(hoverStats.p75)}
            </p>
          )}
          <ul className="space-y-0.5">
            {companiesInYear(report, hoverYear as number).map((row) => (
              <li key={row.ticker} className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-strata-dim">
                  <span className="h-2 w-2 rounded-full" style={{ background: row.color }} aria-hidden="true" />
                  {row.ticker}
                </span>
                <span className="text-strata-fg">{row.intensity === null ? "—" : pct(row.intensity)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
