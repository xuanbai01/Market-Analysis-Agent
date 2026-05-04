/**
 * CashAndCapitalCard — Phase 4.3.A.
 *
 * Cross-section card matching the row-4 leftmost card from
 * `direction-strata.jsx`. Top stack: CapEx + SBC per-share lines from
 * Capital Allocation. Bottom stack: Cash + Debt per-share lines from
 * Quality. Highlight box: Net cash / share = (cash − debt at latest
 * snapshot), colored pos/neg.
 *
 * The card degrades gracefully:
 *
 *   - Either stack alone renders if its sibling lacks data.
 *   - Net cash falls back to em-dash when either snapshot is missing.
 *   - Both stacks empty → just the empty highlight box.
 */
import { formatClaimValue } from "../lib/format";
import {
  extractCapexSbcSeries,
  extractCashDebtSeries,
  extractNetCashPerShare,
} from "../lib/cash-capital-extract";
import type { Section } from "../lib/schemas";
import { MultiLine } from "./MultiLine";

interface Props {
  capAllocSection: Section | undefined;
  qualitySection: Section | undefined;
  /** Phase 4.5.B — read from ``layout_signals.cash_runway_quarters``.
   *  When provided (number, including 0.0), the card grows a "Runway"
   *  stat tile alongside the Net cash highlight. ``null`` / undefined
   *  hides the tile (FCF-positive companies, cache-pre-4.5 reports). */
  runwayQuarters?: number | null;
}

const RUNWAY_RAISE_THRESHOLD = 6;

export function CashAndCapitalCard({
  capAllocSection,
  qualitySection,
  runwayQuarters,
}: Props) {
  const capexSbc = extractCapexSbcSeries(capAllocSection);
  const cashDebt = extractCashDebtSeries(qualitySection);
  const netCash = extractNetCashPerShare(qualitySection);

  const sign = netCash === null ? "neutral" : netCash >= 0 ? "pos" : "neg";
  const colorClass =
    sign === "pos"
      ? "text-strata-pos"
      : sign === "neg"
        ? "text-strata-neg"
        : "text-strata-hi";

  // Net cash / share is a per-share dollar amount — pass the unit hint
  // explicitly so values < $1 don't render as a percent (Phase 4.3.X).
  const netCashLabel =
    netCash === null ? "—" : formatClaimValue(netCash, "usd_per_share");

  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-cashflow">
        Cash &amp; capital · / share
      </div>

      {/* Top stack — CapEx + SBC */}
      {capexSbc.length > 0 && (
        <div className="mb-4">
          <div className="mb-1 flex flex-wrap gap-3 font-mono text-[10px] text-strata-dim">
            {capexSbc.map((s) => (
              <span
                key={s.label}
                className="flex items-center gap-1"
                style={{ color: s.color }}
              >
                ● {s.label}
              </span>
            ))}
          </div>
          <MultiLine series={capexSbc} height={80} showLegend={false} />
        </div>
      )}

      {/* Bottom stack — Cash + Debt */}
      {cashDebt.length > 0 && (
        <div className="mb-4">
          <div className="mb-1 flex flex-wrap gap-3 font-mono text-[10px] text-strata-dim">
            {cashDebt.map((s) => (
              <span
                key={s.label}
                className="flex items-center gap-1"
                style={{ color: s.color }}
              >
                ● {s.label}
              </span>
            ))}
          </div>
          <MultiLine series={cashDebt} height={80} showLegend={false} />
        </div>
      )}

      <div
        data-testid="net-cash-highlight"
        data-sign={sign}
        className="flex items-baseline justify-between rounded-md bg-strata-raise px-3 py-2"
      >
        <span className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
          Net cash / share
        </span>
        <span
          className={`font-mono tabular text-lg font-medium ${colorClass}`}
        >
          {netCashLabel}
        </span>
      </div>

      {/* Phase 4.5.B — runway tile. Only renders when the report's
          layout_signals.cash_runway_quarters is non-null (FCF-burning
          companies). Adds a "raise likely needed" sub-line when
          runway < 6Q. Stays hidden for healthy / FCF-positive names. */}
      {runwayQuarters !== null && runwayQuarters !== undefined && (
        <div
          data-testid="cash-runway-tile"
          className="mt-2 flex items-baseline justify-between rounded-md bg-strata-raise px-3 py-2"
        >
          <div className="flex flex-col">
            <span className="font-mono text-[10px] uppercase tracking-kicker text-strata-risk">
              Cash runway
            </span>
            {runwayQuarters < RUNWAY_RAISE_THRESHOLD && (
              <span className="mt-0.5 text-xs text-strata-dim">
                raise likely needed
              </span>
            )}
          </div>
          <span
            className={`font-mono tabular text-lg font-medium ${
              runwayQuarters < RUNWAY_RAISE_THRESHOLD
                ? "text-strata-neg"
                : "text-strata-hi"
            }`}
          >
            ~{runwayQuarters.toFixed(1)}Q
          </span>
        </div>
      )}
    </section>
  );
}
