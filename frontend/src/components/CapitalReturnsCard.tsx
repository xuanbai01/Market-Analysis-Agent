/**
 * CapitalReturnsCard — what the company does with its cash: what it
 * returns (shareholder yield = dividend + buybacks), whether free cash
 * flow funds it (payout, coverage, FCF yield) and what it reinvests
 * (capex, SBC). Replaces the leftover generic "Capital Allocation"
 * table at the bottom of the dashboard (2026-11 layout pass).
 *
 * The section's analysis prose clamps to three lines with Show more;
 * the one-line card narrative sits at the bottom like the other cards.
 */
import { useState } from "react";

import { extractCapitalReturns } from "../lib/capital-returns-extract";
import type { Section } from "../lib/schemas";
import { NarrativeStrip } from "./NarrativeStrip";

interface Props {
  ticker: string;
  section: Section;
}

export function CapitalReturnsCard({ ticker, section }: Props) {
  const [expanded, setExpanded] = useState(false);
  const r = extractCapitalReturns(section);
  const split = [
    r.dividendYield && `${r.dividendYield} dividend`,
    r.buybackYield && `${r.buybackYield} buybacks`,
  ].filter(Boolean);

  return (
    <section
      data-testid="capital-returns-card"
      className="flex h-full flex-col rounded-md border border-strata-border bg-strata-surface p-5"
    >
      <header className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-cashflow">
        Capital returns · {ticker}
      </header>

      {r.shareholderYield ? (
        <div data-testid="shareholder-yield">
          <p className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">Shareholder yield</p>
          <p className="mt-0.5 font-mono text-2xl text-strata-hi tabular">{r.shareholderYield}</p>
          {split.length > 0 && <p className="font-mono text-[11px] text-strata-dim">{split.join(" + ")}</p>}
        </div>
      ) : (
        split.length > 0 && <p className="font-mono text-sm text-strata-fg">{split.join(" · ")}</p>
      )}

      {r.stats.length > 0 && (
        <dl className="mt-4 grid grid-cols-2 gap-2">
          {r.stats.map((stat) => (
            <div key={stat.label} data-testid="capital-stat" title={stat.description} className="rounded-md bg-strata-raise px-2.5 py-2">
              <dt className="font-mono text-[9px] uppercase tracking-kicker text-strata-muted">{stat.label}</dt>
              <dd className="mt-0.5 font-mono text-sm text-strata-hi tabular">{stat.value}</dd>
            </div>
          ))}
        </dl>
      )}

      {(r.marketCap || r.shortDays) && (
        <p className="mt-3 font-mono text-[11px] text-strata-dim">
          {[r.marketCap && `Market cap ${r.marketCap}`, r.shortDays && `short interest ${r.shortDays} to cover`]
            .filter(Boolean)
            .join(" · ")}
        </p>
      )}

      {/* The analysis paragraph is collapsed: open it would make this the
          tallest card in its row and stretch its neighbours. The one-line
          narrative below carries the takeaway. */}
      {section.summary && (
        <div className="mt-3">
          <button
            type="button"
            aria-expanded={expanded}
            aria-controls={`capital-returns-summary-${ticker}`}
            onClick={() => setExpanded((v) => !v)}
            className="font-mono text-[11px] text-strata-highlight hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-strata-highlight"
          >
            {expanded ? "Hide the analysis" : "Read the analysis"}
          </button>
          {expanded && (
            <p id={`capital-returns-summary-${ticker}`} className="mt-1 text-xs leading-relaxed text-strata-fg">
              {section.summary}
            </p>
          )}
        </div>
      )}

      <NarrativeStrip text={section.card_narrative} />
    </section>
  );
}
