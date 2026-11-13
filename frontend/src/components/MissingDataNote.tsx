/**
 * MissingDataNote — one line under the dashboard header naming what
 * this report asked for and did not get.
 *
 * Cards with nothing to draw return null, so a missing section used to
 * leave no trace beyond a lower confidence badge. Renders nothing when
 * every tool returned data.
 */
import { missingFromAudit, type MissingReason } from "../lib/missing-data";

const REASON_TEXT: Record<MissingReason, string> = {
  empty: "no data",
  failed: "source failed",
};

const REASON_HINT: Record<MissingReason, string> = {
  empty: "The source had nothing for this ticker.",
  failed: "The source could not be read when this report was built. Regenerate to try again.",
};

interface Props {
  audit: readonly string[];
}

export function MissingDataNote({ audit }: Props) {
  const missing = missingFromAudit(audit);
  if (missing.length === 0) return null;
  return (
    <p data-testid="missing-data" className="mb-3 font-mono text-[11px] text-strata-muted">
      Not in this report:{" "}
      {missing.map((item, i) => (
        <span key={item.label} title={REASON_HINT[item.reason]}>
          {i > 0 && " · "}
          <span className="text-strata-fg">{item.label}</span> ({REASON_TEXT[item.reason]})
        </span>
      ))}
    </p>
  );
}
