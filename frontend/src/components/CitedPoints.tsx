/**
 * CitedPoints — an AI read's points, each followed by chips for the
 * figures it cites (value and what it is, the full line on hover). Used by
 * the lens narrative and the options read; both cite by index into their
 * own list of facts.
 */
import { formatClaimValue } from "../lib/format";
import type { Claim, ThesisPoint } from "../lib/schemas";

interface Props {
  points: ThesisPoint[];
  facts: Claim[];
  evidenceTestId: string;
}

export function CitedPoints({ points, facts, evidenceTestId }: Props) {
  return (
    <ul className="mt-4 space-y-3">
      {points.map((point, i) => (
        <li key={i}>
          <p className="text-sm leading-relaxed text-strata-fg">{point.text}</p>
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
        </li>
      ))}
    </ul>
  );
}
