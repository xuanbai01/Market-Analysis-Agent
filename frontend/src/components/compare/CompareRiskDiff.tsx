/**
 * CompareRiskDiff — Phase 4.6.A; redrawn in the 2026-11 chart audit.
 *
 * Side-by-side 10-K risk-factor changes for both tickers, drawn with the
 * dashboard RiskDiffCard's own bars: net paragraphs per topic on one
 * diverging scale (dropped left, added right), shared by both sides so
 * equal bars mean equal changes; the added / dropped / kept fallback
 * when the categorizer hasn't run on a cached report. Returns null when
 * neither ticker has a risk diff so the page collapses.
 *
 * It used to scale each side to its own largest change (a lone ±1 drew
 * a full bar) with a fixed 120 px label column that squeezed the bars
 * to nothing in its narrow column.
 */
import { extractRiskCategoryDeltas, extractRiskDiffBars, type RiskCategoryDelta, type RiskDiffBars } from "../../lib/risk-extract";
import type { ResearchReport } from "../../lib/schemas";
import { AggregateBars, CategoryBars, riskCategoryScale } from "../RiskDiffCard";

interface Props {
  a: ResearchReport;
  b: ResearchReport;
}

interface SidePayload {
  symbol: string;
  categories: RiskCategoryDelta[] | null;
  aggregates: RiskDiffBars | null;
}

function buildPayload(report: ResearchReport): SidePayload | null {
  const section = report.sections.find((s) => s.title === "Risk Factors");
  if (!section) return null;
  const categories = extractRiskCategoryDeltas(section);
  const aggregates = extractRiskDiffBars(section);
  if (!categories && !aggregates) return null;
  return { symbol: report.symbol, categories, aggregates };
}

function Side({ payload, scale, side }: { payload: SidePayload; scale: number; side: "a" | "b" }) {
  return (
    <div data-side-risk={side}>
      <div className="mb-2 font-mono text-xs text-strata-highlight">{payload.symbol}</div>
      {payload.categories ? (
        <CategoryBars deltas={payload.categories} scale={scale} />
      ) : payload.aggregates ? (
        <AggregateBars bars={payload.aggregates} />
      ) : null}
      {payload.aggregates && (
        <p className="mt-2 font-mono text-[11px] text-strata-dim">
          {payload.aggregates.added} added · {payload.aggregates.removed} dropped · {payload.aggregates.kept} kept
        </p>
      )}
    </div>
  );
}

export function CompareRiskDiff({ a, b }: Props) {
  const aPayload = buildPayload(a);
  const bPayload = buildPayload(b);
  if (!aPayload && !bPayload) return null;

  const scale = riskCategoryScale([...(aPayload?.categories ?? []), ...(bPayload?.categories ?? [])]);

  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-risk">
        10-K risk factors · vs prior year · one scale for both
      </div>
      <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
        {aPayload && <Side payload={aPayload} scale={scale} side="a" />}
        {bPayload && <Side payload={bPayload} scale={scale} side="b" />}
      </div>
    </section>
  );
}
