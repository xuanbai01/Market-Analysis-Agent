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
}

export function CashAndCapitalCard({
  capAllocSection,
  qualitySection,
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

  const netCashLabel = netCash === null ? "—" : formatClaimValue(netCash);

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
    </section>
  );
}
