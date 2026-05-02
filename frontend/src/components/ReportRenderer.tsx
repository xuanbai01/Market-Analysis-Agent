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
import {
  extractMedian,
  extractSubject,
  groupPeers,
} from "../lib/peer-grouping";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { Sparkline } from "./Sparkline";

// SectionChart + PeerScatter are the only Recharts consumers; lazy-
// loading them keeps recharts (~100 KB gz) out of the initial bundle.
// Login screen + dashboard skeleton paint fast; the chart chunk loads
// after the report data arrives. Vite's code-splitter hoists recharts
// into a shared vendor chunk so SectionChart and PeerScatter share
// the runtime cost of recharts (verified via `npm run build`).
const SectionChart = lazy(() => import("./SectionChart"));
const PeerScatter = lazy(() => import("./PeerScatter"));

interface Props {
  report: ResearchReport;
}

export function ReportRenderer({ report }: Props) {
  return (
    <article className="space-y-4">
      <header className="flex flex-wrap items-baseline justify-between gap-3 border-b border-slate-200 pb-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight text-slate-900">
            {report.symbol}
          </h2>
          <p className="text-xs text-slate-500">
            Generated {formatTimestamp(report.generated_at)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs uppercase tracking-wide text-slate-500">
            Overall
          </span>
          <ConfidenceBadge confidence={report.overall_confidence} />
        </div>
      </header>

      {report.sections.length === 0 ? (
        <p className="text-sm text-slate-500">No sections returned.</p>
      ) : (
        report.sections.map((section) => (
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
  report,
}: {
  section: Section;
  report: ResearchReport;
}) {
  // Phase 3.3.B — pick a "headline" Claim (or pair, for Earnings) and
  // render a SectionChart at the top of the card. Returns null when
  // the section has no spec, no matching claim, or insufficient
  // history; in those cases the card falls back to its pre-3.3.B
  // shape (header + summary + claims table).
  const featured = featuredClaim(section);

  // Phase 3.3.C — Peers section gets a PeerScatter above its claims
  // table. Subject metrics (P/E, gross margin) are extracted from
  // sibling Valuation + Quality sections at the renderer level so
  // PeerScatter stays a pure visual component. Falls back to peers-
  // only scatter in EARNINGS focus mode (no Quality section).
  const isPeers = section.title === "Peers";
  const peers = isPeers ? groupPeers(section.claims) : [];
  const median = isPeers ? extractMedian(section.claims) ?? undefined : undefined;
  const subject = isPeers ? extractSubject(report) ?? undefined : undefined;
  const showScatter = isPeers && peers.length > 0;

  return (
    <section className="rounded-md border border-slate-200 bg-white p-5 shadow-sm">
      <header className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-slate-900">
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

      {showScatter && (
        <div className="mb-4">
          <Suspense
            fallback={
              <div
                className="hidden sm:block"
                style={{ height: 240, width: 360 }}
              />
            }
          >
            <PeerScatter peers={peers} subject={subject} median={median} />
          </Suspense>
        </div>
      )}

      {section.summary && (
        <p className="mb-4 text-sm leading-relaxed text-slate-700">
          {section.summary}
        </p>
      )}

      {section.claims.length > 0 && <ClaimsTable claims={section.claims} />}
    </section>
  );
}

function ClaimsTable({ claims }: { claims: Claim[] }) {
  return (
    <div className="overflow-hidden rounded-md border border-slate-200">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
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
        <tbody className="divide-y divide-slate-100">
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
    <tr className="hover:bg-slate-50">
      <td className="px-3 py-2 text-slate-700">{claim.description}</td>
      <td className="px-3 py-2 text-right font-mono text-slate-900">
        {formatClaimValue(claim.value)}
      </td>
      <td className="hidden px-3 py-2 sm:table-cell">
        {claim.history.length >= 2 ? (
          <Sparkline
            history={claim.history}
            ariaLabel={`Trend for ${claim.description}`}
          />
        ) : null}
      </td>
      <td className="px-3 py-2 text-xs text-slate-500">
        {claim.source.url ? (
          <a
            href={claim.source.url}
            target="_blank"
            rel="noopener noreferrer"
            className="text-slate-700 underline decoration-slate-300 underline-offset-2 hover:text-slate-900 hover:decoration-slate-500"
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
