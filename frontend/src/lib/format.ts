/**
 * Shared display helpers. Keep formatting decisions out of components
 * so we can change "show as percent" or "abbreviate large numbers" in
 * one place.
 */
import type { ClaimUnit, ClaimValue } from "./schemas";

/**
 * Render a claim value for display.
 *
 * Phase 4.3.X — when the backend stamps a ``unit`` hint on the Claim,
 * dispatch on it deterministically. This fixes three classes of bugs
 * from the legacy heuristic-only path:
 *
 * - **ROE-class** — fraction-form values ≥ 1 used to fall through to
 *   the plain-number branch and silently drop the % suffix
 *   ("141% ROE" rendered as "1.41"). With ``unit: "fraction"`` we
 *   ×100 and append "%" regardless of magnitude.
 * - **Per-share dollar** — a < $1 per-share value (typical for
 *   capital-light megacaps) used to be treated as a fraction
 *   ("$0.16 capex/share" rendered as "16.00%"). ``unit:
 *   "usd_per_share"`` prepends "$" and shows 2 decimals.
 * - **Percent-form yield** — yfinance returns ``dividendYield`` in
 *   percent-form (0.39 means "0.39%"), but the legacy heuristic
 *   ×100'd it again ("39.00%"). ``unit: "percent"`` skips the ×100.
 *
 * When ``unit`` is ``undefined`` or ``null`` (pre-4.3.X cached rows),
 * the legacy heuristic is preserved unchanged — this makes the change
 * safe for stale JSONB rows in the cache table.
 *
 * The eval rubric on the backend understands these same display rules
 * (``tests/evals/rubric.py::_matches_claim``), so what the user sees
 * here is what the rubric accepts there. If you tweak this, tweak the
 * rubric too.
 */
export function formatClaimValue(
  value: ClaimValue,
  unit?: ClaimUnit | null,
): string {
  if (value === null) return "—";

  // ── Unit-aware dispatch (Phase 4.3.X) ─────────────────────────────
  // Run unit handling before the legacy paths so a typed Claim never
  // accidentally falls through. Each branch returns; the legacy logic
  // below it is the fallback for unit-less cached rows.
  if (unit) {
    if (typeof value === "boolean") {
      // Boolean values ignore the unit (no useful unit applies).
      return value ? "yes" : "no";
    }

    if (unit === "string" || unit === "date") {
      // Pure passthrough — the backend already produced a display string.
      return typeof value === "string" ? value : String(value);
    }

    // The remaining units expect a numeric value. Strings should not
    // appear here in practice; if they do, fall through to the
    // legacy path so we don't crash.
    if (typeof value === "number") {
      const n = value;
      const abs = Math.abs(n);

      switch (unit) {
        case "fraction":
          // ROE 1.41 → "141.00%", margin 0.74 → "74.00%". Apply ×100
          // unconditionally — that's the whole point of this unit.
          return `${(n * 100).toFixed(2)}%`;
        case "percent":
          // Already in percent-form (yfinance dividendYield style):
          // 0.39 → "0.39%". No ×100.
          return `${n.toFixed(2)}%`;
        case "usd_per_share": {
          // 0.16 → "$0.16", -0.04 → "-$0.04", 3.48 → "$3.48".
          const sign = n < 0 ? "-" : "";
          return `${sign}$${abs.toFixed(2)}`;
        }
        case "usd": {
          // Plain USD: abbreviate large magnitudes, $ prefix always.
          const sign = n < 0 ? "-" : "";
          if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
          if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
          if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
          return `${sign}$${abs.toFixed(2)}`;
        }
        case "ratio":
          // P/E etc. — plain decimal, 2 places, no suffix.
          return n.toFixed(2);
        case "shares":
          // Abbreviated count, no $ prefix.
          if (abs >= 1e12) return `${(n / 1e12).toFixed(2)}T`;
          if (abs >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
          if (abs >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
          return n.toLocaleString();
        case "count":
          // Locale-grouped integer (default to integer rendering).
          return Number.isInteger(n)
            ? n.toLocaleString()
            : n.toFixed(2);
        case "basis_points":
          // 0.0007 (= 7 bps) → "7 bps". 0.012 → "120 bps".
          return `${(n * 10000).toFixed(0)} bps`;
      }
    }
  }

  // ── Legacy heuristic (pre-4.3.X cached rows, ``unit`` absent) ────
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
