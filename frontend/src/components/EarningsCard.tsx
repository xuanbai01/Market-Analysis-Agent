/**
 * EarningsCard — replaces the Earnings section's claim-table with a
 * richer card. Phase 4.1.
 *
 * Header row:
 *   left:  eyebrow "EARNINGS · 20 QUARTERS" + bold "X of N beat consensus"
 *   right: "Next print" eyebrow + accent date + "AFTER MARKET" tag
 *
 * Middle:
 *   EpsBars chart (20 bars, beat/miss color-coded, estimate ticks)
 *
 * Bottom row:
 *   3 stat tiles: Beat rate / Surprise μ / EPS TTM
 *
 * Reads claim values via description matching (same philosophy as
 * featured-claim.ts / hero-extract.ts). Falls back gracefully when
 * any individual claim is missing.
 */
import { formatClaimValue } from "../lib/format";
import type { Claim, ClaimHistoryPoint, Section } from "../lib/schemas";
import { EpsBars } from "./EpsBars";
import { NarrativeStrip } from "./NarrativeStrip";

interface DistressedFlags {
  /** Phase 4.5.B — when true, surface the "● BOTTOM DECILE" annotation
   *  beside the X-of-N beat-consensus headline. Driven by the
   *  research report's ``layout_signals.beat_rate_below_30pct``. */
  beat_rate_below_30pct?: boolean;
}

interface Props {
  section: Section;
  /** Phase 4.5.B — distressed-mode flags read by the card. Optional;
   *  omitting leaves the card in healthy-default rendering. */
  distressed?: DistressedFlags;
}

const DESC_EPS_ACTUAL = "Reported EPS (latest quarter)";
const DESC_EPS_ESTIMATE = "Consensus EPS estimate (latest quarter, going in)";
const DESC_NEXT_REPORT = "Next earnings report date (expected)";
const DESC_BEAT_COUNT_PREFIX = "Number of EPS beats over the last 20 quarters";
const DESC_AVG_SURPRISE_PREFIX = "Average EPS surprise (%)";

function findClaimByDescription(
  claims: readonly Claim[],
  predicate: (description: string) => boolean,
): Claim | undefined {
  return claims.find((c) => predicate(c.description));
}

function findExact(
  claims: readonly Claim[],
  description: string,
): Claim | undefined {
  return findClaimByDescription(claims, (d) => d === description);
}

function findStartsWith(
  claims: readonly Claim[],
  prefix: string,
): Claim | undefined {
  return findClaimByDescription(claims, (d) => d.startsWith(prefix));
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function epsTTM(history: ClaimHistoryPoint[]): number | null {
  // Sum of last 4 quarters' actual EPS.
  if (history.length < 4) return null;
  const last4 = history.slice(-4);
  return last4.reduce((acc, p) => acc + p.value, 0);
}

export function EarningsCard({ section, distressed }: Props) {
  const claims = section.claims;
  const epsActualClaim = findExact(claims, DESC_EPS_ACTUAL);
  const epsEstimateClaim = findExact(claims, DESC_EPS_ESTIMATE);
  const nextReportClaim = findExact(claims, DESC_NEXT_REPORT);
  const beatCountClaim = findStartsWith(claims, DESC_BEAT_COUNT_PREFIX);
  const avgSurpriseClaim = findStartsWith(claims, DESC_AVG_SURPRISE_PREFIX);

  const actualHistory = epsActualClaim?.history ?? [];
  const estimateHistory = epsEstimateClaim?.history ?? [];
  const beatCount = isFiniteNumber(beatCountClaim?.value)
    ? (beatCountClaim?.value as number)
    : null;
  const avgSurprise = isFiniteNumber(avgSurpriseClaim?.value)
    ? (avgSurpriseClaim?.value as number)
    : null;
  const ttm = epsTTM(actualHistory);
  const totalQuarters = actualHistory.length || 20;

  const beatRate = beatCount !== null ? beatCount / totalQuarters : null;

  const nextReportValue =
    typeof nextReportClaim?.value === "string" ? nextReportClaim.value : null;

  return (
    // No mb-6 here — the parent grid in SymbolDetailPage owns vertical
    // spacing via gap-6 so a card-level margin would double up on the
    // last row of every grid.
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-earnings">
            Earnings · {totalQuarters} quarters
          </div>
          {beatCount !== null && (
            <div className="mt-1 flex flex-wrap items-baseline gap-2 text-base font-medium text-strata-hi">
              <span>{beatCount} of {totalQuarters} beat consensus</span>
              {distressed?.beat_rate_below_30pct && (
                <span
                  data-testid="earnings-bottom-decile"
                  className="inline-flex items-center gap-1 rounded-md bg-strata-raise px-2 py-0.5 font-mono text-[10px] uppercase tracking-kicker"
                >
                  <span className="text-strata-neg">●</span>
                  <span className="text-strata-fg">Bottom decile</span>
                </span>
              )}
            </div>
          )}
        </div>
        {nextReportValue && (
          <div className="text-right">
            <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
              Next print
            </div>
            <div className="mt-1 font-mono text-base font-medium text-strata-highlight">
              {nextReportValue}
            </div>
            <div className="font-mono text-[9px] uppercase tracking-kicker text-strata-dim">
              after market
            </div>
          </div>
        )}
      </header>

      {actualHistory.length > 0 ? (
        <EpsBars actual={actualHistory} estimate={estimateHistory} />
      ) : (
        <div className="flex h-[120px] items-center justify-center font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
          No earnings history available
        </div>
      )}

      <div className="mt-4 grid grid-cols-3 gap-3 border-t border-strata-line pt-4">
        <StatTile
          label="Beat rate"
          value={beatRate !== null ? `${Math.round(beatRate * 100)}%` : "—"}
          accent={
            beatRate !== null && beatRate >= 0.6
              ? "text-strata-pos"
              : beatRate !== null && beatRate < 0.4
                ? "text-strata-neg"
                : "text-strata-hi"
          }
        />
        <StatTile
          label="Surprise μ"
          value={
            avgSurprise !== null
              ? `${avgSurprise >= 0 ? "+" : ""}${avgSurprise.toFixed(1)}%`
              : "—"
          }
          accent={
            avgSurprise !== null && avgSurprise > 0
              ? "text-strata-pos"
              : avgSurprise !== null && avgSurprise < 0
                ? "text-strata-neg"
                : "text-strata-hi"
          }
        />
        <StatTile
          label="EPS TTM"
          value={ttm !== null ? formatClaimValue(ttm) : "—"}
        />
      </div>

      {/*
        Phase 4.3.B.1 — RecentPrints mini-table. The 3 stat tiles plus
        the chart left ~600 px of canvas below the EarningsCard before
        the row's height matched its partner (QualityCard, ~1200 px).
        Surfacing the last 4 quarters' actual / estimate / surprise
        gives substantive content + closes most of the gap.
      */}
      {actualHistory.length >= 1 && (
        <RecentPrints actual={actualHistory} estimate={estimateHistory} />
      )}

      <NarrativeStrip text={section.card_narrative} />
    </section>
  );
}

function RecentPrints({
  actual,
  estimate,
}: {
  actual: ClaimHistoryPoint[];
  estimate: ClaimHistoryPoint[];
}) {
  const estByPeriod = new Map<string, number>();
  for (const e of estimate) estByPeriod.set(e.period, e.value);

  const last4 = actual.slice(-4);
  return (
    <div
      data-testid="recent-prints"
      className="mt-4 overflow-hidden rounded-md border border-strata-line"
    >
      <div className="flex items-center justify-between bg-strata-raise px-3 py-2">
        <span className="font-mono text-[10px] uppercase tracking-kicker text-strata-earnings">
          Recent prints · last {last4.length}Q
        </span>
        <span className="font-mono text-[9px] uppercase tracking-kicker text-strata-dim">
          actual · estimate · surprise
        </span>
      </div>
      <table className="w-full text-sm">
        <tbody className="divide-y divide-strata-line">
          {last4.map((row) => {
            const est = estByPeriod.get(row.period);
            const surprise =
              est !== undefined && est !== 0
                ? ((row.value - est) / Math.abs(est)) * 100
                : null;
            const surpriseClass =
              surprise === null
                ? "text-strata-dim"
                : surprise > 0
                  ? "text-strata-pos"
                  : surprise < 0
                    ? "text-strata-neg"
                    : "text-strata-fg";
            return (
              <tr
                key={row.period}
                data-row="recent-print"
                className="hover:bg-strata-raise"
              >
                <td className="px-3 py-2 font-mono text-xs text-strata-dim">
                  {row.period}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular text-strata-hi">
                  {row.value.toFixed(2)}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular text-strata-fg">
                  {est !== undefined ? est.toFixed(2) : "—"}
                </td>
                <td
                  className={`px-3 py-2 text-right font-mono tabular ${surpriseClass}`}
                >
                  {surprise !== null
                    ? `${surprise >= 0 ? "+" : ""}${surprise.toFixed(1)}%`
                    : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function StatTile({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: string;
}) {
  return (
    <div className="rounded-md bg-strata-raise p-3">
      <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
        {label}
      </div>
      <div
        className={`mt-1 font-mono tabular text-xl font-medium ${accent ?? "text-strata-hi"}`}
      >
        {value}
      </div>
    </div>
  );
}
