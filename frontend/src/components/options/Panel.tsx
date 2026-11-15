/** A titled card on the options page. */
import type { ReactNode } from "react";

export function Panel({ title, children, testId }: { title: string; children: ReactNode; testId?: string }) {
  return (
    // min-w-0: a grid item otherwise grows to its chart's first (fallback)
    // width, and the chart then measures that instead of the page.
    <section data-testid={testId} className="mb-6 min-w-0 rounded-md border border-strata-border bg-strata-surface p-5">
      <h2 className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">{title}</h2>
      {children}
    </section>
  );
}
