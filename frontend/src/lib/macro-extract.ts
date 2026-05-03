/**
 * macro-extract — pulls FRED-series panels out of the Macro section.
 * Phase 4.3.A.
 *
 * The backend (app/services/macro.py) emits 3 claims per series:
 *
 *   "{label} (latest observation)"   ← value-bearing, history-bearing
 *   "{label} observation date"       ← string value, no history
 *   "Human-readable label for FRED series {id}"  ← static metadata
 *
 * Plus 2 metadata claims at the section root (sector, series_list)
 * which we ignore here.
 *
 * One panel per series:
 *
 *   { id, label, latest, history, observationDate }
 *
 * Series whose latest value is non-numeric or whose history is empty
 * are skipped so the renderer doesn't have to defend against them.
 */
import type { ClaimHistoryPoint, Section } from "./schemas";

const VALUE_SUFFIX = " (latest observation)";
const DATE_SUFFIX = " observation date";
const METADATA_DESCRIPTIONS = new Set([
  "Resolved sector for macro context",
  "FRED series chosen for this sector",
]);

export interface MacroPanelSpec {
  /** FRED series id, when discoverable. May be null when only the
   *  human-readable label is present. */
  id: string | null;
  /** Human-readable label (e.g. "10Y Treasury yield"). */
  label: string;
  /** Latest numeric observation. */
  latest: number;
  /** Per-period history; renders as the area chart. */
  history: ClaimHistoryPoint[];
  /** Observation date string (e.g. "2024-04-01"); null when not present. */
  observationDate: string | null;
}

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/**
 * Build one panel per FRED series found in the Macro section.
 *
 * The contract is value-claim-driven: every claim whose description
 * ends in " (latest observation)" defines a series. The label is the
 * description's prefix; the matching " observation date" claim (if
 * present and string-valued) provides the observationDate.
 */
export function extractMacroPanels(section: Section): MacroPanelSpec[] {
  // Build a date-by-label lookup once.
  const dateByLabel = new Map<string, string>();
  for (const claim of section.claims) {
    if (METADATA_DESCRIPTIONS.has(claim.description)) continue;
    if (!claim.description.endsWith(DATE_SUFFIX)) continue;
    const label = claim.description.slice(
      0,
      claim.description.length - DATE_SUFFIX.length,
    );
    if (typeof claim.value === "string") {
      dateByLabel.set(label, claim.value);
    }
  }

  const panels: MacroPanelSpec[] = [];
  for (const claim of section.claims) {
    if (METADATA_DESCRIPTIONS.has(claim.description)) continue;
    if (!claim.description.endsWith(VALUE_SUFFIX)) continue;
    const label = claim.description.slice(
      0,
      claim.description.length - VALUE_SUFFIX.length,
    );
    if (!isFiniteNumber(claim.value)) continue;
    if (claim.history.length === 0) continue;
    panels.push({
      id: idForLabel(section, label),
      label,
      latest: claim.value,
      history: claim.history,
      observationDate: dateByLabel.get(label) ?? null,
    });
  }
  return panels;
}

/**
 * Best-effort FRED series-id lookup. The backend emits a metadata
 * claim "Human-readable label for FRED series {id}" with the label
 * as ``value``; we walk those to find the id whose value matches our
 * label. Returns null when no metadata claim matches.
 */
function idForLabel(section: Section, label: string): string | null {
  const PREFIX = "Human-readable label for FRED series ";
  for (const claim of section.claims) {
    if (
      claim.description.startsWith(PREFIX) &&
      typeof claim.value === "string" &&
      claim.value === label
    ) {
      return claim.description.slice(PREFIX.length);
    }
  }
  return null;
}
