/**
 * ReportRenderer — the fallback for report sections with no dedicated
 * card.
 *
 * Every section the backend builds today has its own card, so
 * SymbolDetailPage excludes all of them and this renders nothing. It
 * stays so that a section added on the backend shows up on the page —
 * title, confidence, summary and a claims table — before its card
 * exists.
 *
 * Layout: a header with symbol + overall confidence + generated_at,
 * then one card per section. Each card has:
 *
 * - Title + per-section confidence badge
 * - Free-form summary prose (single paragraph from the LLM)
 * - A claims table — one row per claim, with description, formatted
 *   value, a trend cell, and a source link if the claim's Source
 *   carries a URL.
 *
 * The summary prose comes from the LLM and the rubric guarantees
 * every number in it is also present in ``claims``. We deliberately
 * keep the prose plain text (no markdown) — the LLM is instructed
 * the same way (see app/services/research_orchestrator.py).
 *
 * The Trend column hides on viewports smaller than ``sm`` (640 px) —
 * a small trend next to a number on a phone is more noise than
 * signal. Hidden via Tailwind's ``hidden sm:table-cell``.
 */
import type { Claim, ResearchReport, Section } from "../lib/schemas";
import { formatClaimValue, formatTimestamp } from "../lib/format";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { TrendCell } from "./TrendCell";

interface Props {
  report: ResearchReport;
  /** Sections drawn by dedicated cards, left out here. */
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
          <SectionCard key={section.title} section={section} />
        ))
      )}
    </article>
  );
}

function SectionCard({ section }: { section: Section }) {
  return (
    <section
      data-section-anchor={section.title}
      className="rounded-md border border-strata-border bg-strata-surface p-5"
    >
      <header className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-lg font-semibold text-strata-hi">
          {section.title}
        </h3>
        <ConfidenceBadge confidence={section.confidence} size="sm" />
      </header>

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
            {/* Trend column — hidden on phones; a trend is illegible at
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
        <TrendCell history={claim.history} unit={claim.unit} label={claim.description} />
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
