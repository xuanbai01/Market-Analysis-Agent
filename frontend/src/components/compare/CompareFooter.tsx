/**
 * CompareFooter — Phase 4.6.A.
 *
 * Honest-scope strip at the bottom of the Compare page. Two columns:
 *
 *   WHAT SURVIVES THE COMPARE   — what the page does carry across both
 *   WHAT'S CUT                  — what the symbol-detail layout has
 *                                 that compare deliberately drops
 *
 * Pure presentation; no data plumbing. Copy will iterate without test
 * churn since the test only asserts the two headers, not the body.
 */

const SURVIVES = [
  "Hero (price + sector + market cap)",
  "Valuation matrix (P/E FWD · P/S · EV/EBITDA)",
  "Quality matrix (Gross · Op · FCF margin · ROIC)",
  "Operating margin time series",
  "Per-share growth (5Y rebased)",
  "10-K risk diff",
];

const CUT = [
  "Macro panel (cross-ticker, not per-ticker)",
  "Full Business descriptions",
  "News list",
  "Cash & capital deep dive",
  "Peer scatter (this IS the comparison)",
];

export function CompareFooter() {
  return (
    <section
      data-card="compare-footer"
      className="rounded-md border border-strata-border bg-strata-surface p-5"
    >
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div>
          <div className="mb-2 font-mono text-[10px] uppercase tracking-kicker text-strata-pos">
            What survives the compare
          </div>
          <ul className="space-y-1 text-xs text-strata-dim">
            {SURVIVES.map((line) => (
              <li key={line}>· {line}</li>
            ))}
          </ul>
        </div>
        <div>
          <div className="mb-2 font-mono text-[10px] uppercase tracking-kicker text-strata-muted">
            What&apos;s cut
          </div>
          <ul className="space-y-1 text-xs text-strata-dim">
            {CUT.map((line) => (
              <li key={line}>· {line}</li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}
