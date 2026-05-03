import type { Confidence } from "../lib/schemas";

// Phase 4.0 — restyled for dark theme via Strata state colors.
// Uses tinted accent backgrounds (12% opacity) over the surface, so
// the badge reads as a status pill on the dark canvas without
// fighting the 9 category accents reserved for metric coloring.
const STYLES: Record<Confidence, string> = {
  high: "bg-strata-pos/15 text-strata-pos ring-strata-pos/30",
  medium: "bg-strata-cashflow/15 text-strata-cashflow ring-strata-cashflow/30",
  low: "bg-strata-neg/15 text-strata-neg ring-strata-neg/30",
};

interface Props {
  confidence: Confidence;
  /** Optional smaller variant used inside section headers. */
  size?: "sm" | "md";
}

export function ConfidenceBadge({ confidence, size = "md" }: Props) {
  const sizing = size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm";
  return (
    <span
      className={`inline-flex items-center rounded-full font-medium ring-1 ring-inset ${sizing} ${STYLES[confidence]}`}
    >
      {confidence}
    </span>
  );
}
