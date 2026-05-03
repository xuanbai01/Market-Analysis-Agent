/**
 * QualityCard — replaces ReportRenderer's Quality section. Phase 4.2.
 *
 * Layout:
 *
 *   header (kicker "QUALITY · <ticker>" + per-section confidence)
 *   3 MetricRings (ROE / ROIC / FCF margin)
 *   MultiLine chart (gross / operating / FCF margin trio)
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

import { formatClaimValue } from "../lib/format";
import {
  extractAllQualityClaims,
  extractMarginSeries,
  extractPrimaryQualityClaims,
  extractQualityRings,
} from "../lib/quality-extract";
import type { Claim, Section } from "../lib/schemas";
import { ConfidenceBadge } from "./ConfidenceBadge";
import { MetricRing } from "./MetricRing";
import { MultiLine } from "./MultiLine";
import { Sparkline } from "./Sparkline";

interface Props {
  ticker: string;
  section: Section;
}

export function QualityCard({ ticker, section }: Props) {
  const rings = extractQualityRings(section);
  const series = extractMarginSeries(section);
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
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <header className="mb-4 flex items-start justify-between gap-3">
        <div>
          <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-quality">
            Quality · {ticker}
          </div>
          {section.summary && (
            <p className="mt-2 max-w-2xl text-sm leading-relaxed text-strata-fg">
              {section.summary}
            </p>
          )}
        </div>
        <ConfidenceBadge confidence={section.confidence} size="sm" />
      </header>

      {/* 3 MetricRings — bail to em-dash when value missing. ROE / ROIC
          / FCF margin are all fraction-form values; pass the unit hint
          explicitly so high-ROE companies (e.g. AAPL ROE = 1.41) render
          as "141.00%" instead of dropping the % suffix. */}
      <div className="mb-5 grid grid-cols-3 gap-3 border-y border-strata-line py-5">
        <MetricRing
          label="ROE"
          value={rings.roe !== null ? formatClaimValue(rings.roe, "fraction") : "—"}
          ratio={rings.roe}
          accentClass="text-strata-quality"
        />
        <MetricRing
          label="ROIC TTM"
          value={rings.roic !== null ? formatClaimValue(rings.roic, "fraction") : "—"}
          ratio={rings.roic}
          sub={rings.roic !== null && rings.roic > 0.4 ? "top decile" : null}
          accentClass="text-strata-quality"
        />
        <MetricRing
          label="FCF margin"
          value={
            rings.fcfMargin !== null
              ? formatClaimValue(rings.fcfMargin, "fraction")
              : "—"
          }
          ratio={rings.fcfMargin}
          accentClass="text-strata-cashflow"
        />
      </div>

      {/* Multi-line margin chart. */}
      {series.length >= 2 && (
        <div className="mb-5">
          {/*
            Phase 4.3.X — MARGINS sub-kicker (cosmetic backlog from PR
            #50). Inline current GM / OM / FCF values matching the
            legend chips below. Shows snapshot point values (not
            history-last) since that's what the rings + claim table
            also display, so the user reads one consistent number per
            metric across the whole card.
          */}
          <div
            data-testid="quality-margins-subkicker"
            className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1 font-mono text-[10px] uppercase tracking-kicker"
          >
            <span className="text-strata-quality">Margins · 5Y</span>
            <MarginsInline section={section} />
          </div>
          <MultiLine series={series} />
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
        {claim.history.length >= 2 ? (
          <Sparkline
            history={claim.history}
            ariaLabel={`Trend for ${claim.description}`}
          />
        ) : null}
      </td>
    </tr>
  );
}

/** Inline GM / OM / FCF values for the MARGINS sub-kicker.
 *  Reads the section's snapshot claim values (claim.value), formats
 *  via the unit-aware formatter, and renders three colored chips that
 *  echo the MultiLine legend below. */
function MarginsInline({ section }: { section: Section }) {
  const find = (desc: string) =>
    section.claims.find((c) => c.description === desc);
  const gm = find("Gross margin");
  const om = find("Operating margin");
  const fcf = find("Free cash flow margin");
  return (
    <span className="flex flex-wrap items-baseline gap-x-2.5 text-strata-dim">
      {gm && (
        <span>
          <span className="mr-1 text-strata-quality">●</span>
          GM {formatClaimValue(gm.value, gm.unit ?? "fraction")}
        </span>
      )}
      {om && (
        <span>
          <span className="mr-1 text-strata-quality opacity-80">●</span>
          OM {formatClaimValue(om.value, om.unit ?? "fraction")}
        </span>
      )}
      {fcf && (
        <span>
          <span className="mr-1 text-strata-cashflow">●</span>
          FCF {formatClaimValue(fcf.value, fcf.unit ?? "fraction")}
        </span>
      )}
    </span>
  );
}
