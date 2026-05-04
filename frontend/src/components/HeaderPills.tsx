/**
 * HeaderPills — Phase 4.5.A.
 *
 * Diagnostic pills rendered at the page top-right of /symbol/:ticker
 * when ``layout_signals`` flags distress. Each signal maps to a single
 * pill; multiple signals stack horizontally. Returns ``null`` when
 * every flag is healthy so healthy mature names (NVDA, AAPL) render
 * with a clean header.
 *
 * Design (per ``docs/screenshots/image-1777831007647.png``):
 *
 *   ● UNPROFITABLE · TTM           — red dot, strata-neg accent
 *   ⚠ LIQUIDITY WATCH              — warning glyph, strata-risk accent
 *   ● BOTTOM DECILE BEAT RATE      — strata-neg
 *   ▲ DEBT RISING · CASH FALLING   — strata-risk
 *
 * The runway threshold is < 6 quarters (≈ 18 months — short enough
 * that a capital raise becomes the dominant Q1 question).
 *
 * ``is_unprofitable_ttm`` and ``gross_margin_negative`` collapse to a
 * single UNPROFITABLE pill — both fire on Rivian-class names and
 * doubling up adds visual noise without information.
 */
import type { LayoutSignals } from "../lib/schemas";

interface Props {
  signals: LayoutSignals;
}

interface PillSpec {
  label: string;
  glyph: string;
  glyphClass: string;
  accentClass: string;
}

const RUNWAY_WATCH_THRESHOLD = 6;

const PILL_UNPROFITABLE: PillSpec = {
  label: "UNPROFITABLE · TTM",
  glyph: "●",
  glyphClass: "text-strata-neg",
  accentClass: "text-strata-fg",
};

const PILL_LIQUIDITY: PillSpec = {
  label: "LIQUIDITY WATCH",
  glyph: "⚠",
  glyphClass: "text-strata-risk",
  accentClass: "text-strata-fg",
};

const PILL_BEAT_RATE: PillSpec = {
  label: "BOTTOM DECILE BEAT RATE",
  glyph: "●",
  glyphClass: "text-strata-neg",
  accentClass: "text-strata-fg",
};

const PILL_DEBT_RISING: PillSpec = {
  label: "DEBT RISING · CASH FALLING",
  glyph: "▲",
  glyphClass: "text-strata-risk",
  accentClass: "text-strata-fg",
};

function pickPills(signals: LayoutSignals): PillSpec[] {
  const out: PillSpec[] = [];
  // Collapse both unprofitability conditions to one pill.
  if (signals.is_unprofitable_ttm || signals.gross_margin_negative) {
    out.push(PILL_UNPROFITABLE);
  }
  if (
    signals.cash_runway_quarters !== null &&
    signals.cash_runway_quarters < RUNWAY_WATCH_THRESHOLD
  ) {
    out.push(PILL_LIQUIDITY);
  }
  if (signals.beat_rate_below_30pct) {
    out.push(PILL_BEAT_RATE);
  }
  if (signals.debt_rising_cash_falling) {
    out.push(PILL_DEBT_RISING);
  }
  return out;
}

export function HeaderPills({ signals }: Props) {
  const pills = pickPills(signals);
  if (pills.length === 0) return null;

  return (
    <div
      data-testid="header-pills"
      className="flex flex-wrap items-center justify-end gap-2"
    >
      {pills.map((pill) => (
        <span
          key={pill.label}
          data-pill="header-pill"
          className="inline-flex items-center gap-1.5 rounded-md bg-strata-raise px-2.5 py-1 font-mono text-[10px] uppercase tracking-kicker"
        >
          <span className={pill.glyphClass}>{pill.glyph}</span>
          <span className={pill.accentClass}>{pill.label}</span>
        </span>
      ))}
    </div>
  );
}
