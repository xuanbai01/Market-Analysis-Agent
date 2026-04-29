import type { Confidence } from "../lib/schemas";

const STYLES: Record<Confidence, string> = {
  high: "bg-emerald-100 text-emerald-800 ring-emerald-200",
  medium: "bg-amber-100 text-amber-800 ring-amber-200",
  low: "bg-red-100 text-red-800 ring-red-200",
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
