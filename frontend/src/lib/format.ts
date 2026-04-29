/**
 * Shared display helpers. Keep formatting decisions out of components
 * so we can change "show as percent" or "abbreviate large numbers" in
 * one place.
 */
import type { ClaimValue } from "./schemas";

/**
 * Render a claim value for display. Numbers get sensible formatting:
 *
 * - Fractions in ``[-1, 1]`` rendered as percentages (e.g. 0.18 → "18.00%").
 *   This catches yields, margins, growth rates — the bulk of the
 *   percentage-shaped metrics our tools produce.
 * - Magnitudes ≥ 1e6 abbreviated (T / B / M).
 * - Booleans rendered as "yes" / "no" (less jarring than "true" / "false"
 *   in a financial context).
 * - Null rendered as an em-dash so a missing value doesn't look like a
 *   layout break.
 *
 * The eval rubric on the backend understands these same display rules
 * (``tests/evals/rubric.py::_matches_claim``), so what the user sees
 * here is what the rubric accepts there. If you tweak this, tweak the
 * rubric too.
 */
export function formatClaimValue(value: ClaimValue): string {
  if (value === null) return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "string") return value;

  // numbers from here down
  const n = value;
  const abs = Math.abs(n);

  if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`;

  // Decimal-shaped fractions in [-1, 1] (excluding 0): show as %.
  if (abs > 0 && abs <= 1) {
    return `${(n * 100).toFixed(2)}%`;
  }

  // Plain numbers: 2 decimals if it has any fractional part, otherwise integer.
  if (Number.isInteger(n)) return n.toLocaleString();
  return n.toFixed(2);
}

/** Format an ISO timestamp for sidebar display ("Apr 29, 14:05"). */
export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
