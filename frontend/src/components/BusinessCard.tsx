/**
 * BusinessCard — Phase 4.4.A.
 *
 * Single ContextBand card surfacing yfinance's longBusinessSummary
 * alongside HQ + employee count. Renders nothing when the summary is
 * empty so the ContextBand can collapse cleanly for thinly-covered
 * tickers.
 *
 * Long summaries (yfinance often returns several paragraphs) clamp to
 * three lines with a "Show more" toggle, as the 4.4.A spec intended
 * (tasks/dogfood-2026-11.md #3).
 */
import { useState } from "react";

import { extractBusinessInfo } from "../lib/business-extract";
import type { Section } from "../lib/schemas";

interface Props {
  ticker: string;
  section: Section;
}

/** Roughly three lines at the card's width; shorter text never clamps. */
export const BUSINESS_SUMMARY_CLAMP_CHARS = 280;

export function BusinessCard({ ticker, section }: Props) {
  const info = extractBusinessInfo(section);
  const [expanded, setExpanded] = useState(false);
  if (!info.summary) return null;
  const long = info.summary.length > BUSINESS_SUMMARY_CLAMP_CHARS;

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
      <p
        id={`business-summary-${ticker}`}
        data-testid="business-summary"
        className={`text-sm leading-relaxed text-strata-fg ${long && !expanded ? "line-clamp-3" : ""}`}
      >
        {info.summary}
      </p>
      {long && (
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={`business-summary-${ticker}`}
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 font-mono text-[11px] text-strata-highlight hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
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
