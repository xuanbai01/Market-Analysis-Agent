/**
 * missing-data — what a report asked for and did not get.
 *
 * The backend records each tool's outcome in ``tool_calls_audit``:
 * ``"<tool>: ok"``, ``"<tool>: empty"`` (ran, found nothing) or
 * ``"<tool>: error/<Type>"`` (raised). A card with nothing to draw
 * returns null, so without this the only trace of a missing section
 * was a lower confidence badge: XOM lost its 10-K risk card and its
 * ten-year history after a reorganization moved its filings, and the
 * page did not say so (dogfood 2026-11 #18).
 */

export type MissingReason = "empty" | "failed";

export interface MissingItem {
  /** What the reader would call it ("ten-year history"). */
  label: string;
  reason: MissingReason;
}

/** Tool → what the reader would call its output. ``null``: no card
 *  shows it, so its absence is not worth a line. */
const TOOL_LABELS: Record<string, string | null> = {
  extract_10k_risks_diff: "10-K risk changes",
  extract_10k_business: null,
  fetch_annual_history: "ten-year history",
  fetch_macro: "macro",
  fetch_news: "news",
  fetch_peers: "peer comparison",
  fetch_earnings: "earnings",
  fetch_fundamentals: "fundamentals",
  fetch_business_info: "business profile",
  fetch_insider_activity: "insider activity",
};

function labelFor(tool: string): string | null {
  if (tool in TOOL_LABELS) return TOOL_LABELS[tool];
  return tool.replace(/^(fetch|extract)_/, "").replace(/_/g, " ");
}

/** The tools that came back empty or failed, in audit order. */
export function missingFromAudit(audit: readonly string[]): MissingItem[] {
  const items: MissingItem[] = [];
  for (const entry of audit) {
    const split = entry.indexOf(": ");
    if (split <= 0) continue;
    const tool = entry.slice(0, split);
    const status = entry.slice(split + 2);
    const reason: MissingReason | null =
      status === "empty" ? "empty" : status.startsWith("error") ? "failed" : null;
    if (reason === null) continue;
    const label = labelFor(tool);
    if (label === null || items.some((item) => item.label === label)) continue;
    items.push({ label, reason });
  }
  return items;
}
