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

import { Link } from "react-router-dom";

import { extractBusinessInfo } from "../lib/business-extract";
import { ROUTES } from "../lib/routes";
import type { Section } from "../lib/schemas";

interface Props {
  ticker: string;
  section: Section;
  /** 2026-11 layout pass: the comparison set, as links to each peer. */
  sector?: string | null;
  peers?: string[];
}

/** "consumer_staples" → "Consumer staples". */
function sectorLabel(sector: string): string {
  const words = sector.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Roughly three lines at the card's width; shorter text never clamps. */
export const BUSINESS_SUMMARY_CLAMP_CHARS = 280;

export function BusinessCard({ ticker, section, sector = null, peers = [] }: Props) {
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
    <section className="flex h-full flex-col rounded-md border border-strata-border bg-strata-surface p-5">
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
          className="mt-1 self-start font-mono text-[11px] text-strata-highlight hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
      {/* Facts pinned to the bottom: when the row stretches the card,
          the spare height sits between the summary and these. */}
      <div className="mt-auto">
      {metaParts.length > 0 && (
        <div
          data-testid="business-meta"
          className="mt-3 font-mono text-[11px] text-strata-dim"
        >
          {metaParts.join(" · ")}
        </div>
      )}
      {(sector || peers.length > 0) && (
        <dl data-testid="business-peers" className="mt-4 space-y-2 border-t border-strata-line pt-3 text-xs">
          {sector && (
            <div className="flex gap-2">
              <dt className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">Sector</dt>
              <dd className="text-strata-fg">{sectorLabel(sector)}</dd>
            </div>
          )}
          {peers.length > 0 && (
            <div>
              <dt className="mb-1.5 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
                Compared with
              </dt>
              <dd className="flex flex-wrap gap-1.5">
                {peers.map((peer) => (
                  <Link
                    key={peer}
                    to={ROUTES.symbol(peer)}
                    title={`Open ${peer}`}
                    className="rounded border border-strata-border bg-strata-raise px-2 py-0.5 font-mono text-[11px] text-strata-fg transition hover:border-strata-highlight/60 hover:text-strata-hi focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight"
                  >
                    {peer}
                  </Link>
                ))}
              </dd>
            </div>
          )}
        </dl>
      )}
      </div>
    </section>
  );
}
