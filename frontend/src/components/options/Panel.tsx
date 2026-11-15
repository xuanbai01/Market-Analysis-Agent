/**
 * A titled card on the options page: the title (with a ⓘ when there's
 * something to explain), a one-sentence takeaway with its figures in bold,
 * the chart, and a small stats table under it.
 */
import type { ReactNode } from "react";

import type { Sentence } from "../../lib/options-text";
import { InfoTip, SentenceText, StatsTable } from "./chart-kit";

interface Props {
  title: string;
  children: ReactNode;
  testId?: string;
  info?: string;
  summary?: Sentence | null;
  stats?: { label: string; value: string }[];
}

export function Panel({ title, children, testId, info, summary, stats }: Props) {
  return (
    // min-w-0: a grid item otherwise grows to its chart's first (fallback)
    // width, and the chart then measures that instead of the page.
    <section data-testid={testId} className="mb-6 min-w-0 rounded-md border border-strata-border bg-strata-surface p-5">
      <h2 className="mb-2 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
        {title}
        {info && <InfoTip label={title} text={info} />}
      </h2>
      {summary && (
        <p data-testid={testId ? `${testId}-summary` : undefined} className="mb-3 text-sm leading-relaxed text-strata-fg">
          <SentenceText sentence={summary} />
        </p>
      )}
      {children}
      {stats && <StatsTable rows={stats} testId={testId ? `${testId}-stats` : undefined} />}
    </section>
  );
}
