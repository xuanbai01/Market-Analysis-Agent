/**
 * QualityCard — replaces ReportRenderer's Quality section. Phase 4.2.
 *
 * Layout:
 *
 *   header (kicker "QUALITY · <ticker>" + per-section confidence)
 *   3 headline stat tiles (ROE / ROIC / FCF margin), each naming its
 *   basis. They were rings until the 2026-11 chart audit: a ring reads
 *   as "out of 100%", but these have no ceiling — AAPL's 141% ROE drew
 *   a full ring, RIVN's negatives drew empty ones — and "top decile"
 *   under ROIC had no data behind it.
 *   MultiLine chart (gross / operating / FCF margin, by quarter)
 *   summary prose (when present)
 *   claims table — 6 default + "Show all 16" disclosure
 *
 * The 6 default claims = ROE, Gross margin, Operating margin, FCF
 * margin, ROIC TTM, Net profit margin (in display order). Tapping
 * "Show all" expands to every claim in the section; tapping
 * "Show fewer" collapses back. The disclosure button is hidden when
 * there are 6 or fewer claims to begin with.
 */
import { useState } from "react";

import {
  fractionPct,
  fractionPctTick,
  pointsChange,
} from "../lib/chart-format";
import { formatClaimValue } from "../lib/format";
import {
  extractAllQualityClaims,
  extractMarginSeries,
  extractPrimaryQualityClaims,
  extractQualityRings,
} from "../lib/quality-extract";
import type { Claim, Section } from "../lib/schemas";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { MultiLine } from "./MultiLine";
import { NarrativeStrip } from "./NarrativeStrip";
import { TrendCell } from "./TrendCell";

interface Props {
  ticker: string;
  section: Section;
}

export function QualityCard({ ticker, section }: Props) {
  const rings = extractQualityRings(section);
  const series = extractMarginSeries(section);
  // The margin histories are quarterly (~5 quarters from yfinance);
  // the sub-kicker used to say "5Y".
  const marginPeriods = Math.max(0, ...series.map((s) => s.history.length));
  const primaryClaims = extractPrimaryQualityClaims(section);
  const allClaims = extractAllQualityClaims(section);
  const [expanded, setExpanded] = useState(false);
  // Only collapse to "primary 6" when there's actually something hidden
  // worth a disclosure. If the section has <= 6 claims total, just show
  // them all — collapsing to 3 of 5 with a "Show all 5" button is more
  // friction than information.
  const compact = allClaims.length > 6;
  const visibleClaims = compact && !expanded ? primaryClaims : allClaims;
  const showDisclosure = compact;

  return (
    // No mb-6 — vertical spacing comes from the parent grid's gap-6.
    <section className="flex h-full flex-col rounded-md border border-strata-border bg-strata-surface p-5">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-quality">
          Quality · {ticker}
        </div>
        <ConfidenceBadge confidence={section.confidence} size="sm" />
      </header>

      {/* 2026-11 layout pass: full-width card, two columns at lg —
          the read (prose, rings, strip) beside the evidence (margins
          chart, metric table). */}
      <div className="grid flex-1 grid-cols-1 gap-x-8 gap-y-5 lg:grid-cols-2">
        <div className="flex flex-col">
          {section.summary && (
            <p className="mb-5 text-sm leading-relaxed text-strata-fg">
              {section.summary}
            </p>
          )}

          <div
            data-testid="quality-headline-stats"
            className="grid grid-cols-3 gap-3 border-y border-strata-line py-5"
          >
            <HeadlineStat label="ROE" value={rings.roe} basis="trailing 12 months" />
            <HeadlineStat label="ROIC" value={rings.roic} basis="trailing 12 months" />
            <HeadlineStat label="FCF margin" value={rings.fcfMargin} basis="latest quarter" />
          </div>

          <NarrativeStrip text={section.card_narrative} />
        </div>

        <div>
          {/* Multi-line margin chart. */}
          {series.length >= 2 && (
            <div className="mb-5">
              {/* Quarterly points: the line's end labels carry the latest
                  quarter. The header used to repeat the snapshot values,
                  but gross margin's snapshot is trailing-12-month (62.32%
                  for KO) while its line ends at the latest quarter
                  (63.2%) — two "GM" numbers on one card. */}
              <div
                data-testid="quality-margins-subkicker"
                className="mb-2 font-mono text-[10px] uppercase tracking-kicker text-strata-quality"
              >
                Margins by quarter · {marginPeriods}Q
              </div>
              <MultiLine
                series={series}
                includeZero
                formatValue={fractionPct}
                formatTick={fractionPctTick}
                formatChange={pointsChange}
                ariaLabel="Gross, operating and FCF margin by quarter"
              />
            </div>
          )}

          {/* Claims table. */}
          {visibleClaims.length > 0 && (
            <div className="overflow-hidden rounded-md border border-strata-line">
              <table className="w-full text-sm">
                <thead className="bg-strata-raise text-left text-xs uppercase tracking-wide text-strata-muted">
                  <tr>
                    <th className="px-3 py-2 font-medium">Metric</th>
                    <th className="px-3 py-2 font-medium text-right">Value</th>
                    <th
                      scope="col"
                      className="hidden px-3 py-2 font-medium sm:table-cell"
                    >
                      Trend
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-strata-line">
                  {visibleClaims.map((claim, i) => (
                    <ClaimRow key={`${claim.description}-${i}`} claim={claim} />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {showDisclosure && (
            <div className="mt-3 flex justify-end">
              <button
                type="button"
                onClick={() => setExpanded((x) => !x)}
                className="font-mono text-[11px] uppercase tracking-kicker text-strata-dim transition hover:text-strata-fg"
                aria-expanded={expanded}
              >
                {expanded
                  ? `Show fewer · ${primaryClaims.length}`
                  : `Show all · ${allClaims.length}`}
              </button>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}

function ClaimRow({ claim }: { claim: Claim }) {
  return (
    <tr data-row="quality-claim" className="hover:bg-strata-raise">
      <td className="px-3 py-2 text-strata-fg">{claim.description}</td>
      <td className="px-3 py-2 text-right font-mono tabular text-strata-hi">
        {formatClaimValue(claim.value, claim.unit)}
      </td>
      <td className="hidden px-3 py-2 sm:table-cell">
        <TrendCell
          history={claim.history}
          unit={claim.unit}
          label={claim.description}
        />
      </td>
    </tr>
  );
}

/** One headline figure: label, value (red when negative) and what it
 *  covers. Proportional digits — a stat value stands alone. */
function HeadlineStat({
  label,
  value,
  basis,
}: {
  label: string;
  value: number | null;
  basis: string;
}) {
  const negative = value !== null && value < 0;
  return (
    <div data-testid="quality-stat" data-negative={negative ? "true" : "false"}>
      <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">{label}</div>
      <div className={`mt-1 font-mono text-2xl font-medium ${negative ? "text-strata-neg" : "text-strata-hi"}`}>
        {value !== null ? formatClaimValue(value, "fraction") : "—"}
      </div>
      <div className="mt-0.5 text-[11px] text-strata-dim">{basis}</div>
    </div>
  );
}
