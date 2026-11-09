/**
 * LensPage — /lens/:id. One metric across a group of companies over ten
 * years (ADR 0007 layer 3), read top to bottom:
 *
 *   1. What the distribution shows — the AI read, every point citing the
 *      computed facts it quotes (chips)
 *   2. Capex intensity, distribution by year — DistributionChart
 *   3. Capex by company, in dollars — CapexBars
 *   4. The latest year, company by company — a table (also the
 *      accessible view of both charts)
 *   5. How it's built — data source and fiscal-year mapping
 */
import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { fetchLens } from "../../lib/api";
import { formatClaimValue } from "../../lib/format";
import { companiesInYear, companyColor, firstReported, pct, usdBillions } from "../../lib/lens";
import type { LensReport } from "../../lib/schemas";
import { ErrorBanner } from "../ErrorBanner";
import { CapexBars } from "./CapexBars";
import { DistributionChart } from "./DistributionChart";

export function LensPage() {
  const { id = "" } = useParams<{ id: string }>();
  const query = useQuery({
    queryKey: ["lens", id],
    queryFn: () => fetchLens(id),
    staleTime: 10 * 60_000,
  });

  return (
    <div className="mx-auto w-full max-w-screen-xl px-6 py-8 lg:px-8">
      {query.isPending && (
        <div data-testid="lens-loading" className="rounded-md border border-strata-border bg-strata-surface p-6 text-center">
          <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-strata-line border-t-strata-fg" />
          <p className="text-sm text-strata-hi">Building the lens from SEC filings…</p>
          <p className="mt-1 text-xs text-strata-dim">The first load takes about 20 seconds; after that it&apos;s cached for a day.</p>
        </div>
      )}
      {query.error && <ErrorBanner error={query.error} />}
      {query.data && <LensBody report={query.data} />}
    </div>
  );
}

function LensBody({ report }: { report: LensReport }) {
  const first = report.years[0];
  const last = report.years[report.years.length - 1];
  return (
    <>
      <header className="mb-6">
        <p className="font-mono text-[10px] uppercase tracking-kicker text-strata-highlight">
          Lens · {report.companies.length} companies · CY{first}–CY{last}
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight text-strata-hi">{report.title}</h1>
        <p className="mt-1 max-w-3xl text-sm text-strata-dim">{report.description}</p>
      </header>

      <Narrative report={report} />

      <Panel title="Capex intensity — capex as a share of revenue" legend={<Legend report={report} withSummary />}>
        <DistributionChart report={report} />
      </Panel>

      <Panel title="Capex by company, in dollars" legend={<Legend report={report} />}>
        <CapexBars report={report} />
      </Panel>

      <LatestTable report={report} />

      <p data-testid="lens-method" className="mt-6 text-xs leading-relaxed text-strata-muted">
        {report.method}
      </p>
    </>
  );
}

function Narrative({ report }: { report: LensReport }) {
  const narrative = report.narrative;
  if (!narrative) return null;
  return (
    <section data-testid="lens-narrative" className="mb-6 rounded-md border border-strata-border bg-strata-surface p-5">
      <header className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <p className="font-mono text-[10px] uppercase tracking-kicker text-strata-highlight">What the distribution shows</p>
        <p className="font-mono text-[10px] text-strata-muted">AI-written from the computed figures · every point cites them</p>
      </header>
      <p className="text-lg font-medium leading-snug text-strata-hi">{narrative.headline}</p>
      <ul className="mt-4 space-y-3">
        {narrative.points.map((point, i) => (
          <li key={i}>
            <p className="text-sm leading-relaxed text-strata-fg">{point.text}</p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {point.claim_refs.map((ref) => {
                const fact = report.facts[ref.index];
                if (!fact) return null;
                const value = formatClaimValue(fact.value, fact.unit);
                return (
                  <span
                    key={ref.index}
                    data-testid="lens-evidence"
                    title={`${fact.description} = ${value} · ${fact.source.tool}`}
                    className="flex max-w-full items-baseline gap-1.5 rounded border border-strata-border bg-strata-raise px-1.5 py-0.5 font-mono text-[10px]"
                  >
                    <span className="text-strata-hi">{value}</span>
                    <span className="max-w-[14rem] truncate text-strata-muted">{fact.description}</span>
                  </span>
                );
              })}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Panel({ title, legend, children }: { title: string; legend: ReactNode; children: ReactNode }) {
  return (
    <section className="mb-6 rounded-md border border-strata-border bg-strata-surface p-5">
      <h2 className="mb-2 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">{title}</h2>
      {legend}
      <div className="mt-3">{children}</div>
    </section>
  );
}

function Legend({ report, withSummary = false }: { report: LensReport; withSummary?: boolean }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[10px] text-strata-dim" aria-label="Legend">
      {report.companies.map((c, index) => (
        <li key={c.ticker} className="flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: companyColor(index) }} aria-hidden="true" />
          {c.ticker}
        </li>
      ))}
      {withSummary && (
        <>
          <li className="flex items-center gap-1.5">
            <span className="h-0.5 w-4 bg-strata-hi" aria-hidden="true" />
            median
          </li>
          <li className="flex items-center gap-1.5">
            <span className="h-2.5 w-4 rounded-sm bg-strata-highlight/25" aria-hidden="true" />
            middle 50%
          </li>
        </>
      )}
    </ul>
  );
}

function LatestTable({ report }: { report: LensReport }) {
  const last = report.years[report.years.length - 1];
  const rows = companiesInYear(report, last);
  const byTicker = new Map(report.companies.map((c) => [c.ticker, c]));
  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <h2 className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
        CY{last}, company by company
      </h2>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[34rem] text-sm" data-testid="lens-table">
          <thead>
            <tr className="text-left font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
              <th className="pb-2 font-normal">Company</th>
              <th className="pb-2 text-right font-normal">Capex</th>
              <th className="pb-2 text-right font-normal">Capex ÷ revenue</th>
              <th className="pb-2 text-right font-normal">Capex ÷ op. cash flow</th>
              <th className="pb-2 text-right font-normal">Intensity since</th>
            </tr>
          </thead>
          <tbody className="font-mono text-[13px] tabular">
            {rows.map((row) => {
              const company = byTicker.get(row.ticker);
              const start = company ? firstReported(company, report.years) : null;
              const change = start && row.intensity !== null && start.year !== last ? row.intensity - start.intensity : null;
              return (
                <tr key={row.ticker} data-testid="lens-row" className="border-t border-strata-line">
                  <td className="py-2">
                    <span className="flex items-center gap-2 text-strata-hi">
                      <span className="h-2 w-2 rounded-full" style={{ background: row.color }} aria-hidden="true" />
                      {row.ticker}
                      <span className="font-sans text-xs text-strata-muted">{company?.name}</span>
                    </span>
                  </td>
                  <td className="py-2 text-right text-strata-fg">{row.capex === null ? "—" : usdBillions(row.capex)}</td>
                  <td className="py-2 text-right text-strata-fg">{row.intensity === null ? "—" : pct(row.intensity)}</td>
                  <td className="py-2 text-right text-strata-fg">{row.capexToOcf === null ? "—" : pct(row.capexToOcf)}</td>
                  <td className="py-2 text-right text-strata-dim">
                    {change === null || !start
                      ? "—"
                      : `${change >= 0 ? "▲" : "▼"} ${Math.abs(change * 100).toFixed(1)} pts since CY${start.year}`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export default LensPage;
