/**
 * Renders one ResearchReport.
 *
 * Layout: a header with symbol + overall confidence + generated_at,
 * then one card per section. Each card has:
 *
 * - Title + per-section confidence badge
 * - Free-form summary prose (single paragraph from the LLM)
 * - A claims table — one row per claim, with description, formatted
 *   value, **trend sparkline (Phase 3.3.A)**, and a source link if the
 *   claim's Source carries a URL.
 *
 * The summary prose comes from the LLM and the rubric guarantees
 * every number in it is also present in ``claims``. We deliberately
 * keep the prose plain text (no markdown) — the LLM is instructed
 * the same way (see app/services/research_orchestrator.py).
 *
 * ## Phase 3.3.A — Trend column
 *
 * After 3.2.A–F shipped 19+ history-bearing claims, this renderer
 * grew a "Trend" column that shows a tiny inline ``Sparkline`` next
 * to claims whose ``history`` has at least two points. Empty-history
 * claims (peers, risk-paragraph counts, business-section length, etc.)
 * render an empty trend cell so the table layout stays rectangular.
 *
 * The Trend column hides on viewports smaller than ``sm`` (640 px) —
 * a 60 px sparkline next to a number on a phone is more noise than
 * signal. Hidden via Tailwind's ``hidden sm:table-cell``.
 */
import { Suspense, lazy } from "react";

import type { Claim, ResearchReport, Section } from "../lib/schemas";
import { featuredClaim } from "../lib/featured-claim";
import { formatClaimValue, formatTimestamp } from "../lib/format";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { Sparkline } from "./Sparkline";

// SectionChart is the only remaining Recharts consumer in this file
// after Phase 4.2 — Peers moved to PeerScatterV2 (hand-rolled SVG)
// inside ValuationCard. SectionChart still serves Capital Allocation +
// Macro until 4.3 replaces those cards. Lazy-loaded so recharts
// (~100 KB gz) stays out of the main bundle; the chunk loads on demand
// when a section needing a chart appears.
const SectionChart = lazy(() => import("./SectionChart"));

interface Props {
  report: ResearchReport;
  /**
   * Phase 4.1+ — sections to exclude from rendering. Used by
   * SymbolDetailPage to hand certain sections off to dedicated cards
   * (e.g. Earnings → EarningsCard) while ReportRenderer continues to
   * own the rest until 4.2/4.3 replace them too.
   */
  excludeSections?: readonly string[];
}

export function ReportRenderer({ report, excludeSections = [] }: Props) {
  const visibleSections = report.sections.filter(
    (s) => !excludeSections.includes(s.title),
  );
  return (
    <article className="space-y-4">
      <header className="flex flex-wrap items-baseline justify-between gap-3 border-b border-strata-line pb-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-strata-hi">
            {report.symbol}
          </h2>
          <p className="text-xs text-strata-dim">
            Generated {formatTimestamp(report.generated_at)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-strata-muted">
            Overall
          </span>
          <ConfidenceBadge confidence={report.overall_confidence} />
        </div>
      </header>

      {visibleSections.length === 0 ? (
        <p className="text-sm text-strata-dim">No sections returned.</p>
      ) : (
        visibleSections.map((section) => (
          <SectionCard
            key={section.title}
            section={section}
            report={report}
          />
        ))
      )}
    </article>
  );
}

function SectionCard({
  section,
}: {
  section: Section;
  report: ResearchReport;
}) {
  // Phase 3.3.B — pick a "headline" Claim (or pair, for Earnings) and
  // render a SectionChart at the top of the card. Returns null when
  // the section has no spec, no matching claim, or insufficient
  // history; in those cases the card falls back to its pre-3.3.B
  // shape (header + summary + claims table).
  //
  // Phase 4.2 note: Valuation / Quality / Peers / Earnings are all
  // rendered by their dedicated Strata cards (ValuationCard,
  // QualityCard, EarningsCard) and excluded from this renderer. What
  // remains here are Capital Allocation / Risk Factors / Macro until
  // 4.3 lands their dedicated cards too.
  const featured = featuredClaim(section);

  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <header className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-strata-hi">
          {section.title}
        </h3>
        <ConfidenceBadge confidence={section.confidence} size="sm" />
      </header>

      {featured && (
        <div className="mb-4">
          <Suspense
            fallback={
              <div
                className="hidden sm:block"
                style={{ height: 120, width: 300 }}
              />
            }
          >
            <SectionChart
              primary={featured.primary}
              secondary={featured.secondary}
            />
          </Suspense>
        </div>
      )}

      {section.summary && (
        <p className="mb-4 text-sm leading-relaxed text-strata-fg">
          {section.summary}
        </p>
      )}

      {section.claims.length > 0 && <ClaimsTable claims={section.claims} />}
    </section>
  );
}

function ClaimsTable({ claims }: { claims: Claim[] }) {
  return (
    <div className="overflow-hidden rounded-md border border-strata-line">
      <table className="w-full text-sm">
        <thead className="bg-strata-raise text-left text-xs uppercase tracking-wide text-strata-muted">
          <tr>
            <th className="px-3 py-2 font-medium">Metric</th>
            <th className="px-3 py-2 font-medium text-right">Value</th>
            {/* Trend column — hidden on phones; sparkline is illegible at
                that width. Re-introduced at sm: (640 px) and up. */}
            <th
              scope="col"
              className="hidden px-3 py-2 font-medium sm:table-cell"
            >
              Trend
            </th>
            <th className="px-3 py-2 font-medium">Source</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-strata-line">
          {claims.map((claim, i) => (
            <ClaimRow key={`${claim.description}-${i}`} claim={claim} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ClaimRow({ claim }: { claim: Claim }) {
  return (
    <tr className="hover:bg-strata-raise">
      <td className="px-3 py-2 text-strata-fg">{claim.description}</td>
      <td className="px-3 py-2 text-right font-mono tabular text-strata-hi">
        {formatClaimValue(claim.value, claim.unit)}
      </td>
      <td className="hidden px-3 py-2 sm:table-cell">
        {claim.history.length >= 2 ? (
          <Sparkline
            history={claim.history}
            ariaLabel={`Trend for ${claim.description}`}
          />
        ) : null}
      </td>
      <td className="px-3 py-2 text-xs text-strata-dim">
        {claim.source.url ? (
          <a
            href={claim.source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-strata-fg underline decoration-strata-line underline-offset-2 hover:text-strata-hi hover:decoration-strata-border"
          >
            {claim.source.tool}
          </a>
        ) : (
          <span>{claim.source.tool}</span>
        )}
      </td>
    </tr>
  );
}
