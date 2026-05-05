/**
 * CompareRiskDiff — Phase 4.6.A.
 *
 * Side-by-side 10-K risk diff for both tickers. Reuses
 * ``extractRiskCategoryDeltas`` per side; falls back to the aggregate
 * 4-bar shape per side when the Haiku categorizer hasn't run on a
 * cached report. Returns null when both tickers have no risk diff at
 * all so the parent grid can collapse.
 *
 * Rendering is intentionally compact — labels live to the left of each
 * row, deltas to the right. Same color logic as RiskDiffCard's
 * ``CategoryBars``: positive deltas in the risk accent, negative in the
 * quality accent.
 */
import {
  extractRiskCategoryDeltas,
  extractRiskDiffBars,
  type RiskCategoryDelta,
  type RiskDiffBars,
} from "../../lib/risk-extract";
import type { ResearchReport, Section } from "../../lib/schemas";

interface Props {
  a: ResearchReport;
  b: ResearchReport;
}

const COLOR_RISK = "#e57c6e";
const COLOR_QUAL = "#7ad0a6";
const COLOR_DIM = "#5a6473";
const COLOR_HI = "#f5f7fb";

interface SidePayload {
  symbol: string;
  /** When non-null, render the per-category bars; otherwise fall through to aggregate. */
  categories: RiskCategoryDelta[] | null;
  /** Always populated when ``Risk Factors`` claims are present; null when section absent. */
  aggregates: RiskDiffBars | null;
}

function buildPayload(report: ResearchReport): SidePayload | null {
  const section: Section | undefined = report.sections.find(
    (s) => s.title === "Risk Factors",
  );
  if (!section) return null;
  const categories = extractRiskCategoryDeltas(section);
  const aggregates = extractRiskDiffBars(section);
  if (!categories && !aggregates) return null;
  return { symbol: report.symbol, categories, aggregates };
}

function CategoryColumn({ payload }: { payload: SidePayload }) {
  if (payload.categories) {
    const maxAbs = Math.max(1, ...payload.categories.map((d) => Math.abs(d.delta)));
    return (
      <div className="flex flex-col gap-2">
        {payload.categories.map((d) => {
          const color = d.delta >= 0 ? COLOR_RISK : COLOR_QUAL;
          const widthPct = Math.max(2, (Math.abs(d.delta) / maxAbs) * 100);
          return (
            <div
              key={d.category}
              data-row="compare-risk-row"
              className="grid grid-cols-[120px_1fr_36px] items-center gap-2"
            >
              <div className="text-right font-mono text-[10px] text-strata-dim">
                {d.label}
              </div>
              <div className="flex">
                <div
                  className="h-1.5 rounded"
                  style={{ width: `${widthPct}%`, backgroundColor: color }}
                />
              </div>
              <div className="text-right font-mono text-[11px] tabular text-strata-hi">
                {d.delta > 0 ? `+${d.delta}` : `${d.delta}`} ¶
              </div>
            </div>
          );
        })}
      </div>
    );
  }
  // Aggregate fallback: 4 rows.
  const bars = payload.aggregates;
  if (!bars) return null;
  const rows = [
    { label: "Added", value: bars.added, color: COLOR_RISK },
    { label: "Removed", value: bars.removed, color: COLOR_QUAL },
    { label: "Kept", value: bars.kept, color: COLOR_DIM },
    { label: "Char delta", value: bars.charDelta, color: COLOR_HI },
  ];
  const paraMax = Math.max(bars.added, bars.removed, bars.kept) || 1;
  const charScale = Math.abs(bars.charDelta) || 1;
  return (
    <div className="flex flex-col gap-2">
      {rows.map((row) => {
        const scale = row.label === "Char delta" ? charScale : paraMax;
        const widthPct = Math.max(2, (Math.abs(row.value) / scale) * 100);
        return (
          <div
            key={row.label}
            data-row="compare-risk-row"
            data-row-aggregate="true"
            className="grid grid-cols-[120px_1fr_56px] items-center gap-2"
          >
            <div className="text-right font-mono text-[10px] text-strata-dim">
              {row.label}
            </div>
            <div className="flex">
              <div
                className="h-1.5 rounded"
                style={{ width: `${widthPct}%`, backgroundColor: row.color }}
              />
            </div>
            <div className="text-right font-mono text-[11px] tabular text-strata-hi">
              {row.value > 0 && row.label === "Char delta" ? `+${row.value}` : row.value}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function CompareRiskDiff({ a, b }: Props) {
  const aPayload = buildPayload(a);
  const bPayload = buildPayload(b);
  if (!aPayload && !bPayload) return null;

  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-3 font-mono text-[10px] uppercase tracking-kicker text-strata-risk">
        10-K risk diff · both
      </div>
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {aPayload && (
          <div data-side-risk="a">
            <div className="mb-2 font-mono text-xs text-strata-highlight">{aPayload.symbol}</div>
            <CategoryColumn payload={aPayload} />
          </div>
        )}
        {bPayload && (
          <div data-side-risk="b">
            <div className="mb-2 font-mono text-xs text-strata-highlight">{bPayload.symbol}</div>
            <CategoryColumn payload={bPayload} />
          </div>
        )}
      </div>
    </section>
  );
}
