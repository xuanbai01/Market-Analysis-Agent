/**
 * MetricRing — circular ring with center value, label, optional sub-
 * label. Phase 4.2.
 *
 * Used by QualityCard for the ROE / ROIC / FCF margin trio. Hand-rolled
 * SVG (same philosophy as Sparkline / LineChart / EpsBars) so the
 * 4.2 work doesn't lean on Recharts.
 *
 * The ring renders as two concentric arcs: a faint background ring
 * (full circle) plus a colored arc that traces ``ratio`` × full
 * circumference. ``ratio`` is clamped to [0, 1] so values outside the
 * range don't break SVG. ``ratio = null`` renders only the background
 * ring (data unavailable).
 *
 * The center value is whatever the caller passes (typically the
 * formatted percentage from ``formatClaimValue``). Below the ring
 * sits the label (eyebrow); below that, the optional sub-label
 * (annotation like "top decile" or "trailing 12 months").
 */
interface Props {
  /** Display label below the ring (eyebrow). */
  label: string;
  /** Pre-formatted value to render at the ring's center. */
  value: string;
  /** Fraction in [0, 1] that the colored arc traces. ``null`` ⇒ no arc. */
  ratio: number | null;
  /** Optional one-liner annotation below the label. */
  sub?: string | null;
  /** Outer SVG square dimension (px). Default 96. */
  size?: number;
  /** Tailwind class for the ring's accent (text color of the arc). */
  accentClass?: string;
}

const DEFAULT_SIZE = 96;
const STROKE_WIDTH = 7;
const TRACK_COLOR = "rgb(31, 38, 48)"; // strata-line

function clamp01(n: number): number {
  if (!Number.isFinite(n)) return 0;
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}

export function MetricRing({
  label,
  value,
  ratio,
  sub = null,
  size = DEFAULT_SIZE,
  accentClass = "text-strata-quality",
}: Props) {
  const cx = size / 2;
  const cy = size / 2;
  const r = (size - STROKE_WIDTH) / 2;
  const circumference = 2 * Math.PI * r;

  const safeRatio = ratio === null ? 0 : clamp01(ratio);
  const dashOffset = circumference * (1 - safeRatio);

  return (
    <div className="flex flex-col items-center">
      <svg
        data-testid="metric-ring"
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={`${label} ${value}`}
        className="block"
      >
        {/* Background track (full circle). */}
        <circle
          cx={cx}
          cy={cy}
          r={r}
          stroke={TRACK_COLOR}
          strokeWidth={STROKE_WIDTH}
          fill="none"
        />
        {/* Foreground arc. Hidden when ratio is null. */}
        {ratio !== null && (
          <circle
            data-arc="metric-ring-arc"
            cx={cx}
            cy={cy}
            r={r}
            stroke="currentColor"
            strokeWidth={STROKE_WIDTH}
            strokeLinecap="round"
            fill="none"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            className={accentClass}
            transform={`rotate(-90 ${cx} ${cy})`}
          />
        )}
        {/* Center value text. */}
        <text
          x={cx}
          y={cy}
          dominantBaseline="central"
          textAnchor="middle"
          className="fill-strata-hi font-mono"
          style={{ fontSize: size / 5.5, fontWeight: 500 }}
        >
          {value}
        </text>
      </svg>
      <div
        className={`mt-2 font-mono text-[10px] uppercase tracking-kicker ${accentClass}`}
      >
        {label}
      </div>
      {sub && (
        <div className="mt-0.5 text-xs text-strata-dim">{sub}</div>
      )}
    </div>
  );
}
