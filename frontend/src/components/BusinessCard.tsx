/**
 * BusinessCard — Phase 4.4.A.
 *
 * Single ContextBand card surfacing yfinance's longBusinessSummary
 * alongside HQ + employee count. Renders nothing when the summary is
 * empty so the ContextBand can collapse cleanly for thinly-covered
 * tickers.
 */
import { extractBusinessInfo } from "../lib/business-extract";
import type { Section } from "../lib/schemas";

interface Props {
  ticker: string;
  section: Section;
}

export function BusinessCard({ ticker, section }: Props) {
  const info = extractBusinessInfo(section);
  if (!info.summary) return null;

  const metaParts: string[] = [];
  if (info.hq) metaParts.push(info.hq);
  if (info.employeeCount !== null) {
    metaParts.push(`${info.employeeCount.toLocaleString()} employees`);
  }

  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <header className="mb-3 flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-balance">
          Business · {ticker}
        </div>
      </header>
      <p className="text-sm leading-relaxed text-strata-fg">{info.summary}</p>
      {metaParts.length > 0 && (
        <div
          data-testid="business-meta"
          className="mt-3 font-mono text-[11px] text-strata-dim"
        >
          {metaParts.join(" · ")}
        </div>
      )}
    </section>
  );
}
