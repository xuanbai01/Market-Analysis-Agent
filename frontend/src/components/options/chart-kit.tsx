/**
 * Shared pieces for the options page's hand-rolled SVG charts: colors,
 * sizing, scales, axes and the hover tooltip. Calls and puts take the
 * lens palette's first two hues (blue, orange), validated on this surface
 * (#0e1116): colour-blind ΔE 26.8, normal 31.8, contrast over 3:1.
 */
import type { ReactNode } from "react";

import { useMeasuredWidth } from "../../lib/use-measured-width";

export const COLOR = {
  surface: "#0e1116",
  grid: "#1f2630",
  axis: "#8892a0",
  ink: "#e6e9ef",
  hi: "#f5f7fb",
  band: "#7e9ad4",
  neutral: "#9aa4b2",
  call: "#3987e5",
  put: "#d95926",
};
export const FONT = "JetBrains Mono, monospace";
export const PAD = { top: 14, right: 20, bottom: 28, left: 56 };
const FALLBACK_WIDTH = 640;
// Below this the scales would squeeze; the chart scrolls sideways instead.
const MIN_WIDTH = 320;

export function useChartWidth(): [(el: HTMLElement | null) => void, number] {
  const [ref, measured] = useMeasuredWidth();
  return [ref, Math.max(MIN_WIDTH, measured ?? FALLBACK_WIDTH)];
}

export function linear(d0: number, d1: number, r0: number, r1: number): (v: number) => number {
  const span = d1 - d0 || 1;
  return (v) => r0 + ((v - d0) / span) * (r1 - r0);
}

/** Days to expiry on a square-root scale: near-term expiries get room,
 *  and a cone at a constant vol (±σ√T) becomes straight. */
export function sqrtDays(maxDays: number, r0: number, r1: number): (days: number) => number {
  const root = Math.sqrt(Math.max(maxDays, 1));
  return (days) => r0 + (Math.sqrt(Math.max(days, 0)) / root) * (r1 - r0);
}

export const DAY_TICKS = [7, 30, 90, 180, 365];

export function pct(v: number, digits = 1): string {
  return `${(v * 100).toFixed(digits)}%`;
}

export function money(v: number): string {
  return `$${v.toFixed(2)}`;
}

/** "2026-12-11" → "Dec 11"; with a year, "Dec 11, 2026". */
export function shortDate(iso: string, withYear = false): string {
  const [y, m, d] = iso.split("-").map(Number);
  const text = new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
    ...(withYear ? { year: "numeric" } : {}),
  });
  return text;
}

export function AxisText({ x, y, anchor = "end", children }: { x: number; y: number; anchor?: "start" | "middle" | "end"; children: ReactNode }) {
  return (
    <text x={x} y={y} textAnchor={anchor} fontSize={11} fill={COLOR.axis} fontFamily={FONT}>
      {children}
    </text>
  );
}

export function YGrid({ ticks, y, x0, x1, format }: { ticks: number[]; y: (v: number) => number; x0: number; x1: number; format: (v: number) => string }) {
  return (
    <>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={x0} x2={x1} y1={y(t)} y2={y(t)} stroke={COLOR.grid} strokeWidth={1} />
          <AxisText x={x0 - 8} y={y(t) + 4}>
            {format(t)}
          </AxisText>
        </g>
      ))}
    </>
  );
}

export function Tooltip({ testId, left, width, children }: { testId: string; left: number; width: number; children: ReactNode }) {
  return (
    <div
      data-testid={testId}
      className="pointer-events-none absolute top-2 z-10 w-56 rounded-md border border-strata-border bg-strata-surface/95 p-2.5 font-mono text-[11px] text-strata-fg shadow-lg"
      style={{ left: Math.min(Math.max(0, left + 12), width - 230) }}
    >
      {children}
    </div>
  );
}

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="mb-2 flex gap-4 font-mono text-[11px] text-strata-dim">
      {items.map((item) => (
        <span key={item.label} className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: item.color }} aria-hidden="true" />
          {item.label}
        </span>
      ))}
    </div>
  );
}
