/**
 * ValuationCard — replaces ReportRenderer's Valuation + Peers
 * sections. Phase 4.2.
 *
 * Three-region layout:
 *
 *   header (kicker "VALUATION · <ticker>" + per-section confidence)
 *   summary prose (Valuation summary, falls back to Peers summary)
 *   4-cell matrix: trailing P/E, forward P/E, P/S, EV/EBITDA — each
 *     cell shows subject value, peer median, percentile bar.
 *   PeerScatterV2 below the matrix.
 *
 * The percentile bar is a simple horizontal track with peer min on
 * the left, peer max on the right, a faint tick at the median, and
 * the subject as a colored dot. When percentile data is unavailable
 * (e.g. peer set < 2), only the subject + median are shown as bare
 * text values.
 */
import { formatClaimValue } from "../lib/format";
import {
  extractValuationCells,
  type ValuationCell,
} from "../lib/valuation-extract";
import type { Claim, ResearchReport } from "../lib/schemas";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { PeerScatterV2 } from "./PeerScatterV2";

// Phase 4.3.X — count distinct peer tickers in a Peers section's
// claims. Backend ``fetch_peers`` emits each claim as
// ``<TICKER>: <metric description>``; the "Peer median: ..." claims
// are aggregates, not individual peers. The same ticker may appear
// across multiple metrics (P/E, P/S, EV/EBITDA, GM) — count it once.
function countPeers(claims: readonly Claim[]): number {
  const tickers = new Set<string>();
  for (const c of claims) {
    const m = /^([A-Z][A-Z0-9.\-]{0,9}):\s/.exec(c.description);
    if (m && m[1] && m[1] !== "Peer median") {
      tickers.add(m[1]);
    }
  }
  return tickers.size;
}

interface Props {
  report: ResearchReport;
}

export function ValuationCard({ report }: Props) {
  const cells = extractValuationCells(report);
  const valuation = report.sections.find((s) => s.title === "Valuation");
  const peers = report.sections.find((s) => s.title === "Peers");
  const summary = valuation?.summary || peers?.summary || "";
  const confidence = valuation?.confidence ?? peers?.confidence ?? "low";

  // Build the SubjectPoint expected by PeerScatterV2 from the cells.
  const subject = {
    symbol: report.symbol,
    trailing_pe: cells.find((c) => c.metric === "trailing_pe")?.subject ?? null,
    p_s: cells.find((c) => c.metric === "p_s")?.subject ?? null,
    ev_ebitda: cells.find((c) => c.metric === "ev_ebitda")?.subject ?? null,
    gross_margin: gmSubjectFor(report),
  };

  return (
    // No mb-6 — vertical spacing comes from the parent grid's gap-6.
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-valuation">
            Valuation · {report.symbol}
          </div>
          {summary && (
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-strata-fg">
              {summary}
            </p>
          )}
        </div>
        <ConfidenceBadge confidence={confidence} size="sm" />
      </header>

      {/* 4-cell matrix. */}
      <div className="mb-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
        {cells.map((c) => (
          <MetricCell key={c.metric} cell={c} />
        ))}
      </div>

      {peers && peers.claims.length > 0 && (
        <div
          data-testid="valuation-peer-count"
          className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-dim"
        >
          n = {countPeers(peers.claims)} peers · sector medians
        </div>
      )}

      {/* PeerScatterV2.
          Width constrained so the SVG fits the 2/5 column the
          ValuationCard now lives in (Phase 4.3 layout pass). The
          PeerScatterV2 default is 500px which would overflow the
          card body at lg breakpoints. */}
      {peers && peers.claims.length > 0 && (
        <PeerScatterV2
          peerClaims={peers.claims}
          subject={subject}
          width={380}
          height={260}
        />
      )}
    </section>
  );
}

function gmSubjectFor(report: ResearchReport): number | null {
  const quality = report.sections.find((s) => s.title === "Quality");
  if (!quality) return null;
  const claim = quality.claims.find((c) => c.description === "Gross margin");
  if (!claim || typeof claim.value !== "number" || !Number.isFinite(claim.value)) {
    return null;
  }
  return claim.value;
}

function MetricCell({ cell }: { cell: ValuationCell }) {
  const subjectStr = cell.subject !== null ? formatNum(cell.subject) : "—";
  const medianStr =
    cell.peerMedian !== null ? formatNum(cell.peerMedian) : null;

  return (
    <div
      data-cell="valuation-metric"
      data-testid={`cell-${cell.metric}`}
      className="rounded-md bg-strata-raise p-3"
    >
      <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-valuation">
        {cell.label}
      </div>
      <div className="mt-1 font-mono tabular text-xl font-medium text-strata-hi">
        {subjectStr}
      </div>
      {medianStr && (
        <div className="mt-0.5 font-mono text-[11px] text-strata-dim">
          peer median {medianStr}
        </div>
      )}
      <PercentileBar cell={cell} />
    </div>
  );
}

/** Horizontal percentile bar. min → max with subject + median markers. */
function PercentileBar({ cell }: { cell: ValuationCell }) {
  if (
    cell.subject === null ||
    cell.peerMin === null ||
    cell.peerMax === null ||
    cell.peerMedian === null ||
    cell.peerMin === cell.peerMax
  ) {
    return null;
  }

  // Range spans peer min/max plus the subject if it lies outside.
  const lo = Math.min(cell.peerMin, cell.subject);
  const hi = Math.max(cell.peerMax, cell.subject);
  const span = hi - lo || 1;

  function pctOf(v: number): number {
    return ((v - lo) / span) * 100;
  }

  return (
    <div className="relative mt-2 h-1.5 rounded-full bg-strata-line">
      {/* Peer-range tinted segment. */}
      <div
        className="absolute h-full rounded-full bg-strata-border"
        style={{
          left: `${pctOf(cell.peerMin).toFixed(2)}%`,
          right: `${(100 - pctOf(cell.peerMax)).toFixed(2)}%`,
        }}
      />
      {/* Median tick. */}
      <div
        className="absolute top-1/2 h-3 w-0.5 -translate-x-1/2 -translate-y-1/2 bg-strata-highlight opacity-80"
        style={{ left: `${pctOf(cell.peerMedian).toFixed(2)}%` }}
        aria-hidden="true"
      />
      {/* Subject dot. */}
      <div
        className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-strata-valuation ring-2 ring-strata-canvas"
        style={{ left: `${pctOf(cell.subject).toFixed(2)}%` }}
        aria-label={`Subject percentile ${cell.percentile !== null ? Math.round(cell.percentile * 100) : 0}%`}
      />
    </div>
  );
}

/** Same formatting as formatClaimValue, but always force one decimal
 *  for numeric ratios in the matrix cells (P/E, P/S, EV/EBITDA always
 *  read as 28.5×, never 28). */
function formatNum(n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) < 1000) return n.toFixed(1);
  return formatClaimValue(n);
}
