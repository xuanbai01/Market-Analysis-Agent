/**
 * AnalystViewCard — the report-level read that opens the dashboard
 * (Phase 5, ADR 0007 layer 2; compact layout 2026-11).
 *
 *   headline       one sentence: the central conclusion or tension
 *   Bull | Bear    the strongest evidence each way
 *   What changed | What to watch
 *
 * Each point is one line by default: its title ("Margins still
 * expanding") and its key figure — the value of the first claim it
 * cites, rendered from the data, not written by the model. Clicking a
 * point opens its full sentence and its evidence (claim name + value,
 * each scrolling to the card that shows it); "Show all details" opens
 * every point. Until 2026-11 every point was a 40-word sentence with
 * a row of chips — 982 px and 624 words on KO.
 *
 * Points without a title (reports from before titles, or a title the
 * backend rejected) use their text as the label, clamped to two lines.
 * Refs that no longer resolve are left out. Reports from before the
 * analyst view get a one-line hint to regenerate.
 */
import { useId, useState, type ReactNode } from "react";

import { formatClaimValue } from "../lib/format";
import type { ResearchReport, ThesisPoint } from "../lib/schemas";
import { resolveRef, scrollToSection, shortClaimName, type ResolvedRef } from "../lib/thesis";

interface Props {
  report: ResearchReport;
}

type ListKey = "bull" | "bear" | "changed" | "watch";

const LISTS: { key: ListKey; title: string; marker: ReactNode }[] = [
  { key: "bull", title: "Bull case", marker: <span className="text-strata-pos">▲</span> },
  { key: "bear", title: "Bear case", marker: <span className="text-strata-neg">▼</span> },
  { key: "changed", title: "What changed", marker: <span className="text-strata-dim">◆</span> },
  { key: "watch", title: "What to watch", marker: <span className="text-strata-highlight">◉</span> },
];

function resolved(point: ThesisPoint, report: ResearchReport): ResolvedRef[] {
  return point.claim_refs
    .map((ref) => resolveRef(report, ref))
    .filter((r): r is ResolvedRef => r !== null);
}

export function AnalystViewCard({ report }: Props) {
  const thesis = report.thesis;
  const [open, setOpen] = useState<Set<string>>(() => new Set());

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

  const allKeys = LISTS.flatMap(({ key }) => thesis[key].map((_, i) => `${key}-${i}`));
  const allOpen = allKeys.length > 0 && allKeys.every((k) => open.has(k));
  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const list = (key: ListKey) => {
    const spec = LISTS.find((l) => l.key === key)!;
    return (
      <PointList
        key={key}
        listKey={key}
        title={spec.title}
        marker={spec.marker}
        points={thesis[key]}
        report={report}
        open={open}
        onToggle={toggle}
      />
    );
  };
  const hasLower = thesis.changed.length > 0 || thesis.watch.length > 0;

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
        <div className="flex items-baseline gap-3">
          <p className="hidden font-mono text-[10px] text-strata-muted sm:block">
            AI-written from this report&apos;s data · every point cites it
          </p>
          <button
            type="button"
            onClick={() => setOpen(allOpen ? new Set() : new Set(allKeys))}
            className="font-mono text-[11px] text-strata-highlight hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight"
          >
            {allOpen ? "Hide details" : "Show all details"}
          </button>
        </div>
      </header>
      <p id="analyst-view-headline" className="text-lg font-medium leading-snug text-strata-hi">
        {thesis.headline}
      </p>

      <div className="mt-4 grid grid-cols-1 gap-x-8 gap-y-4 md:grid-cols-2">
        {list("bull")}
        {list("bear")}
      </div>
      {hasLower && (
        <div className="mt-4 grid grid-cols-1 gap-x-8 gap-y-4 border-t border-strata-line pt-4 md:grid-cols-2">
          {list("changed")}
          {list("watch")}
        </div>
      )}
    </section>
  );
}

interface PointListProps {
  listKey: ListKey;
  title: string;
  marker: ReactNode;
  points: ThesisPoint[];
  report: ResearchReport;
  open: Set<string>;
  onToggle: (key: string) => void;
}

function PointList({ listKey, title, marker, points, report, open, onToggle }: PointListProps) {
  if (points.length === 0) return null;
  return (
    <div data-testid="analyst-view-list" data-list={title}>
      <h3 className="mb-1 flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
        <span aria-hidden="true">{marker}</span>
        {title}
      </h3>
      <ul className="-mx-2">
        {points.map((point, i) => (
          <PointRow
            key={i}
            point={point}
            report={report}
            open={open.has(`${listKey}-${i}`)}
            onToggle={() => onToggle(`${listKey}-${i}`)}
          />
        ))}
      </ul>
    </div>
  );
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 12 12"
      className={`h-3 w-3 shrink-0 self-center text-strata-muted transition-transform ${open ? "rotate-90" : ""}`}
    >
      <path d="M4.5 2.5 8 6l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function PointRow({
  point,
  report,
  open,
  onToggle,
}: {
  point: ThesisPoint;
  report: ResearchReport;
  open: boolean;
  onToggle: () => void;
}) {
  const detailId = useId();
  const evidence = resolved(point, report);
  const key = evidence[0];
  const keyFigure = key ? formatClaimValue(key.claim.value, key.claim.unit) : null;
  const label = point.title ?? point.text;

  return (
    <li>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={detailId}
        onClick={onToggle}
        className="flex w-full items-baseline gap-2 rounded px-2 py-1.5 text-left transition-colors hover:bg-strata-raise focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight"
      >
        <Chevron open={open} />
        <span className={`min-w-0 flex-1 text-sm text-strata-fg ${point.title ? "" : "line-clamp-2"}`}>{label}</span>
        {keyFigure && key && (
          // The figure names its claim: the model doesn't always cite
          // first the claim that matches the title ("Unbroken beat
          // streak" beside 11.78% EPS growth), so the figure must say
          // what it is rather than borrow the title's meaning.
          <span className="flex shrink-0 flex-col items-end text-right" title={key.claim.description}>
            <span data-testid="key-figure" className="font-mono text-sm text-strata-hi">
              {keyFigure}
            </span>
            <span
              data-testid="key-figure-label"
              className="max-w-[12rem] truncate font-mono text-[10px] leading-tight text-strata-muted"
            >
              {shortClaimName(key.claim.description)}
            </span>
          </span>
        )}
      </button>
      {open && (
        <div id={detailId} className="mb-2 ml-7 mr-2 mt-0.5">
          {point.title && <p className="text-[13px] leading-relaxed text-strata-dim">{point.text}</p>}
          {evidence.length > 0 && (
            <ul className="mt-1.5 divide-y divide-strata-line border-y border-strata-line">
              {evidence.map(({ section, claim }, i) => {
                const value = formatClaimValue(claim.value, claim.unit);
                return (
                  <li key={i}>
                    <button
                      type="button"
                      data-testid="evidence-row"
                      onClick={() => scrollToSection(section)}
                      title={`${claim.description} = ${value} · ${section} · ${claim.source.tool}`}
                      aria-label={`${claim.description}: ${value}. Show in ${section}`}
                      className="flex w-full items-baseline justify-between gap-3 px-1 py-1 text-left text-xs transition-colors hover:bg-strata-raise focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight"
                    >
                      <span className="text-strata-dim">{claim.description}</span>
                      <span className="shrink-0 font-mono text-strata-hi">{value}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}
