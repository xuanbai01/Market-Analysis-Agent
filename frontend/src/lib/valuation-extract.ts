/**
 * valuation-extract — pure helpers that pull ValuationCard's data
 * out of a ResearchReport. Phase 4.2.
 *
 * The Valuation matrix is a cross-section join: the subject's value
 * for each of the 4 metrics lives in the Valuation section; the peer
 * distribution + median for the same metric lives in the Peers
 * section. ValuationCard renders one cell per metric with the subject
 * vs peer percentile bar.
 *
 * The 4 metrics are picked to maximize cross-peer comparability:
 * trailing P/E, forward P/E, P/S, EV/EBITDA. (PEG is not in
 * ``PEER_METRICS`` on the backend, so it can't carry the percentile
 * bar — we omit it.)
 *
 * Percentile is `count(peer_value <= subject) / peer_count`. When
 * subject is null or the peer set has fewer than 2 numeric values,
 * percentile is null (rank is meaningless).
 */
import type { ResearchReport, Section } from "./schemas";

const DESC_TRAILING_PE = "P/E ratio (trailing 12 months)";
const DESC_FORWARD_PE = "P/E ratio (forward, analyst consensus)";
const DESC_PS = "Price-to-sales ratio (trailing 12 months)";
const DESC_EV_EBITDA = "Enterprise value to EBITDA";

export type ValuationMetricKey =
  | "trailing_pe"
  | "forward_pe"
  | "p_s"
  | "ev_ebitda";

export interface ValuationCell {
  metric: ValuationMetricKey;
  /** Display label for the cell header (kicker eyebrow). */
  label: string;
  /** Description string used to look up subject + peer + median values. */
  description: string;
  subject: number | null;
  peerMedian: number | null;
  peerMin: number | null;
  peerMax: number | null;
  /** Subject's rank within peer values, in [0, 1]. Null when undefined. */
  percentile: number | null;
}

const CELLS: { metric: ValuationMetricKey; label: string; description: string }[] = [
  { metric: "trailing_pe", label: "P/E TTM", description: DESC_TRAILING_PE },
  { metric: "forward_pe", label: "P/E FWD", description: DESC_FORWARD_PE },
  { metric: "p_s", label: "P/S", description: DESC_PS },
  { metric: "ev_ebitda", label: "EV/EBITDA", description: DESC_EV_EBITDA },
];

const PEER_CLAIM_RE = /^([A-Z][A-Z0-9.-]*): (.+)$/;

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

function findSection(
  report: ResearchReport,
  title: string,
): Section | undefined {
  return report.sections.find((s) => s.title === title);
}

function subjectValueFor(
  valuation: Section | undefined,
  description: string,
): number | null {
  if (!valuation) return null;
  const claim = valuation.claims.find((c) => c.description === description);
  if (!claim || !isFiniteNumber(claim.value)) return null;
  return claim.value;
}

function peerValuesFor(
  peers: Section | undefined,
  description: string,
): number[] {
  if (!peers) return [];
  const out: number[] = [];
  for (const claim of peers.claims) {
    const match = PEER_CLAIM_RE.exec(claim.description);
    if (!match) continue;
    const [, symbol, metric] = match;
    if (symbol === "Peer") continue;
    if (metric !== description) continue;
    if (!isFiniteNumber(claim.value)) continue;
    out.push(claim.value);
  }
  return out;
}

function peerMedianFor(
  peers: Section | undefined,
  description: string,
): number | null {
  if (!peers) return null;
  const target = `Peer median: ${description}`;
  const claim = peers.claims.find((c) => c.description === target);
  if (!claim || !isFiniteNumber(claim.value)) return null;
  return claim.value;
}

function percentileOf(
  subject: number | null,
  peerValues: readonly number[],
): number | null {
  if (subject === null) return null;
  if (peerValues.length < 2) return null;
  const below = peerValues.filter((v) => v <= subject).length;
  return below / peerValues.length;
}

/**
 * Build the 4 valuation cells for ValuationCard. Each cell is fully
 * populated even when its data is missing — fields just become null
 * — so the renderer can rely on a stable shape.
 */
export function extractValuationCells(report: ResearchReport): ValuationCell[] {
  const valuation = findSection(report, "Valuation");
  const peers = findSection(report, "Peers");

  return CELLS.map(({ metric, label, description }) => {
    const subject = subjectValueFor(valuation, description);
    const peerValues = peerValuesFor(peers, description);
    const peerMedian = peerMedianFor(peers, description);
    const peerMin = peerValues.length > 0 ? Math.min(...peerValues) : null;
    const peerMax = peerValues.length > 0 ? Math.max(...peerValues) : null;
    const percentile = percentileOf(subject, peerValues);
    return {
      metric,
      label,
      description,
      subject,
      peerMedian,
      peerMin,
      peerMax,
      percentile,
    };
  });
}
