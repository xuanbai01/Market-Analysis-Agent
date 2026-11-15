/**
 * CitedPoints — an AI read's points, each followed by chips for the
 * figures it cites (value and what it is, the full line on hover). Used by
 * the lens narrative and the options read; both cite by index into their
 * own list of facts. ``collapsed`` folds each point's chips behind
 * "Sources (n)": the options read quotes its figures in the sentence, so
 * open chips would show each one twice.
 */
import { formatClaimValue } from "../lib/format";
import type { Claim, ThesisPoint } from "../lib/schemas";

interface Props {
  points: ThesisPoint[];
  facts: Claim[];
  evidenceTestId: string;
  collapsed?: boolean;
}

function Chips({ point, facts, evidenceTestId }: { point: ThesisPoint; facts: Claim[]; evidenceTestId: string }) {
  return (
    <div className="mt-1.5 flex flex-wrap gap-1.5">
      {point.claim_refs.map((ref) => {
        const fact = facts[ref.index];
        if (!fact) return null;
        const value = formatClaimValue(fact.value, fact.unit);
        return (
          <span
            key={ref.index}
            data-testid={evidenceTestId}
            title={`${fact.description} = ${value} · ${fact.source.tool}`}
            className="flex max-w-full items-baseline gap-1.5 rounded border border-strata-border bg-strata-raise px-1.5 py-0.5 font-mono text-[10px]"
          >
            <span className="text-strata-hi">{value}</span>
            <span className="max-w-[14rem] truncate text-strata-muted">{fact.description}</span>
          </span>
        );
      })}
    </div>
  );
}

export function CitedPoints({ points, facts, evidenceTestId, collapsed = false }: Props) {
  return (
    <ul className="mt-4 space-y-3">
      {points.map((point, i) => {
        const cited = point.claim_refs.filter((ref) => facts[ref.index]).length;
        return (
          <li key={i}>
            <p className="text-sm leading-relaxed text-strata-fg">{point.text}</p>
            {collapsed ? (
              cited > 0 && (
                <details data-testid={`${evidenceTestId}-sources`} className="mt-1">
                  <summary className="cursor-pointer font-mono text-[10px] text-strata-muted hover:text-strata-hi">
                    Sources ({cited})
                  </summary>
                  <Chips point={point} facts={facts} evidenceTestId={evidenceTestId} />
                </details>
              )
            ) : (
              <Chips point={point} facts={facts} evidenceTestId={evidenceTestId} />
            )}
          </li>
        );
      })}
    </ul>
  );
}
