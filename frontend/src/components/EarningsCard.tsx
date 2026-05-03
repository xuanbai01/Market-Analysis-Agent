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

interface Props {
  section: Section;
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

export function EarningsCard({ section }: Props) {
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
            <div className="mt-1 text-base font-medium text-strata-hi">
              {beatCount} of {totalQuarters} beat consensus
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
    </section>
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
