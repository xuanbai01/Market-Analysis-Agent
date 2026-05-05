/**
 * CompareMetricRow — Phase 4.6.A.
 *
 * Generic horizontal-bar row for the Compare page's Valuation and
 * Quality blocks. Each cell shows:
 *
 *   [ A's value ]  [ proportional bar A ]  LABEL  [ proportional bar B ]  [ B's value ]
 *
 * The "winning" side (cheaper for valuation, higher for quality) draws
 * its bar in the strata-pos accent; the other side draws in
 * strata-dim. Equal values render both in dim.
 *
 * Bar widths are normalized within each row to the max(|valueA|, |valueB|)
 * so within-row bars are visually comparable; absolute scale is not
 * carried across rows because metrics live on different scales.
 *
 * The "lower = cheaper" / "higher = better" hint at the top of the
 * row group makes the direction explicit without each cell needing
 * its own legend.
 */
import type { CompareMetricCell } from "../../lib/compare-extract";
import { formatClaimValue } from "../../lib/format";

interface Props {
  /** Block title rendered as the kicker eyebrow above the cells. */
  title: string;
  cells: CompareMetricCell[];
}

const COLOR_WIN = "bg-strata-pos/70";
const COLOR_LOSE = "bg-strata-dim/40";
const COLOR_NEUTRAL = "bg-strata-line";

function isFiniteValue(v: number | null): v is number {
  return v !== null && Number.isFinite(v);
}

function pickWinner(cell: CompareMetricCell): "a" | "b" | null {
  if (!isFiniteValue(cell.valueA) || !isFiniteValue(cell.valueB)) return null;
  if (cell.valueA === cell.valueB) return null;
  if (cell.lowerIsBetter) {
    return cell.valueA < cell.valueB ? "a" : "b";
  }
  return cell.valueA > cell.valueB ? "a" : "b";
}

function formatCell(value: number | null, cell: CompareMetricCell): string {
  if (!isFiniteValue(value)) return "—";
  // Margins / ROIC are fractions; valuation ratios are dimensionless.
  // Use the description-driven formatter so display matches the rest
  // of the dashboard (74.8% vs 74.80% kind of consistency).
  if (
    cell.description.toLowerCase().includes("margin") ||
    cell.description.toLowerCase().includes("return on")
  ) {
    return formatClaimValue(value, "fraction");
  }
  return `${value.toFixed(1)}×`;
}

function CellRow({ cell }: { cell: CompareMetricCell }) {
  const winner = pickWinner(cell);
  // Capture as locals so TS narrows to ``number`` for arithmetic below.
  const a = isFiniteValue(cell.valueA) ? cell.valueA : null;
  const b = isFiniteValue(cell.valueB) ? cell.valueB : null;
  const max = Math.max(a !== null ? Math.abs(a) : 0, b !== null ? Math.abs(b) : 0) || 1;
  const widthA = a !== null ? (Math.abs(a) / max) * 100 : 0;
  const widthB = b !== null ? (Math.abs(b) / max) * 100 : 0;
  const aColor = winner === null ? COLOR_NEUTRAL : winner === "a" ? COLOR_WIN : COLOR_LOSE;
  const bColor = winner === null ? COLOR_NEUTRAL : winner === "b" ? COLOR_WIN : COLOR_LOSE;

  return (
    <div
      data-row="compare-metric"
      data-metric-key={cell.key}
      className="grid grid-cols-[80px_1fr_140px_1fr_80px] items-center gap-3"
    >
      <div className="text-right font-mono text-sm tabular text-strata-hi">
        {formatCell(cell.valueA, cell)}
      </div>
      <div className="flex justify-end">
        <div
          className={`h-1.5 rounded-l-full ${aColor}`}
          style={{ width: `${widthA}%` }}
        />
      </div>
      <div className="text-center font-mono text-[10px] uppercase tracking-kicker text-strata-dim">
        {cell.label}
      </div>
      <div className="flex justify-start">
        <div
          className={`h-1.5 rounded-r-full ${bColor}`}
          style={{ width: `${widthB}%` }}
        />
      </div>
      <div className="font-mono text-sm tabular text-strata-hi">
        {formatCell(cell.valueB, cell)}
      </div>
    </div>
  );
}

export function CompareMetricRow({ title, cells }: Props) {
  if (cells.length === 0) return null;
  // All cells in a block share the same direction; read it from the first.
  const lowerIsBetter = cells[0].lowerIsBetter;
  const hint = lowerIsBetter ? "lower = cheaper" : "higher = better";

  return (
    <section className="rounded-md border border-strata-border bg-strata-surface p-5">
      <div className="mb-4 flex items-center justify-between">
        <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-highlight">
          {title}
        </div>
        <div className="font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
          {hint}
        </div>
      </div>
      <div className="flex flex-col gap-3">
        {cells.map((cell) => (
          <CellRow key={cell.key} cell={cell} />
        ))}
      </div>
    </section>
  );
}
