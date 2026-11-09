/**
 * AnalystViewCard — the report-level read that opens the dashboard
 * (Phase 5, ADR 0007 layer 2).
 *
 *   headline       one sentence: the central conclusion or tension
 *   Bull | Bear    the strongest evidence each way
 *   What changed   what moved over the past year
 *   What to watch  the metric that would confirm or break the case
 *
 * Every point carries chips for the claims it relies on (value + name);
 * a chip scrolls to the card that shows that claim. Chips whose ref no
 * longer resolves are left out. Reports from before the analyst view
 * shipped get a one-line hint to regenerate.
 */
import type { ReactNode } from "react";

import { formatClaimValue } from "../lib/format";
import type { ResearchReport, ThesisPoint } from "../lib/schemas";
import { resolveRef, scrollToSection } from "../lib/thesis";

interface Props {
  report: ResearchReport;
}

export function AnalystViewCard({ report }: Props) {
  const thesis = report.thesis;
  if (!thesis) {
    return (
      <section
        data-testid="analyst-view-missing"
        className="mb-6 rounded-md border border-dashed border-strata-border px-5 py-3 text-xs text-strata-muted"
      >
        <span className="font-mono uppercase tracking-kicker">Analyst view</span> · not in this
        report yet. Use Regenerate above to add it.
      </section>
    );
  }

  return (
    <section
      data-testid="analyst-view"
      aria-labelledby="analyst-view-headline"
      className="mb-6 rounded-md border border-strata-border bg-strata-surface p-5"
    >
      <header className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-mono text-[10px] uppercase tracking-kicker text-strata-highlight">
          Analyst view · {report.symbol}
        </p>
        <p className="font-mono text-[10px] text-strata-muted">
          AI-written from this report&apos;s data · every point cites it
        </p>
      </header>
      <p id="analyst-view-headline" className="text-lg font-medium leading-snug text-strata-hi">
        {thesis.headline}
      </p>

      <div className="mt-5 grid grid-cols-1 gap-x-8 gap-y-5 md:grid-cols-2">
        <PointList
          title="Bull case"
          marker={<span className="text-strata-pos">▲</span>}
          points={thesis.bull}
          report={report}
        />
        <PointList
          title="Bear case"
          marker={<span className="text-strata-neg">▼</span>}
          points={thesis.bear}
          report={report}
        />
        <PointList
          title="What changed"
          marker={<span className="text-strata-dim">◆</span>}
          points={thesis.changed}
          report={report}
        />
        <PointList
          title="What to watch"
          marker={<span className="text-strata-highlight">◉</span>}
          points={thesis.watch}
          report={report}
        />
      </div>
    </section>
  );
}

interface PointListProps {
  title: string;
  marker: ReactNode;
  points: ThesisPoint[];
  report: ResearchReport;
}

function PointList({ title, marker, points, report }: PointListProps) {
  if (points.length === 0) return null;
  return (
    <div data-testid="analyst-view-list" data-list={title}>
      <h3 className="mb-2 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
        <span aria-hidden="true">{marker}</span>
        {title}
      </h3>
      <ul className="space-y-3">
        {points.map((point, i) => (
          <li key={i}>
            <p className="text-sm leading-relaxed text-strata-fg">{point.text}</p>
            <Evidence point={point} report={report} />
          </li>
        ))}
      </ul>
    </div>
  );
}

function Evidence({ point, report }: { point: ThesisPoint; report: ResearchReport }) {
  const resolved = point.claim_refs
    .map((ref) => resolveRef(report, ref))
    .filter((r): r is NonNullable<typeof r> => r !== null);
  if (resolved.length === 0) return null;
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {resolved.map(({ section, claim }, i) => {
        const value = formatClaimValue(claim.value, claim.unit);
        return (
          <button
            key={i}
            type="button"
            data-testid="evidence-chip"
            onClick={() => scrollToSection(section)}
            title={`${claim.description} = ${value} · ${section} · ${claim.source.tool}`}
            aria-label={`${claim.description}: ${value}. Show in ${section}`}
            className="flex max-w-full items-baseline gap-1.5 rounded border border-strata-border bg-strata-raise px-1.5 py-0.5 font-mono text-[10px] transition-colors hover:border-strata-highlight/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight"
          >
            <span className="text-strata-hi">{value}</span>
            {/* Narrow so a point's chips sit side by side; the full name
                is in the tooltip and the accessible label. */}
            <span className="max-w-[10rem] truncate text-strata-muted">{claim.description}</span>
          </button>
        );
      })}
    </div>
  );
}
