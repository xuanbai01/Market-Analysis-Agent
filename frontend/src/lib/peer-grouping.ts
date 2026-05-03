/**
 * peer-grouping — pure helpers for the Peers section's PeerScatter /
 * PeerScatterV2.
 *
 * Phase 3.3.C introduced the original (P/E × Gross Margin)-fixed
 * helpers; Phase 4.2 generalizes them across any pair of metric
 * descriptions so PeerScatterV2 can pivot axes without re-parsing
 * every claim per render.
 *
 * The legacy ``groupPeers`` / ``extractMedian`` keep the original
 * ``{symbol, pe, margin}`` shape and call into the new generic
 * helpers under the hood — old call sites continue to work.
 *
 * ## Why descriptions, not keys
 *
 * Same reason as ``featured-claim`` / ``hero-extract``: the Pydantic
 * schema flattens ``dict[str, Claim]`` into ``Section.claims:
 * list[Claim]`` and the stable backend keys (``AMD.trailing_pe``, …)
 * don't survive the round-trip. Descriptions are stable strings
 * defined in ``app/services/peers.py::_DESCRIPTIONS`` and
 * ``app/services/fundamentals.py::_DESCRIPTIONS``; tests pin them so
 * a backend rename fails loudly.
 */
import type { Claim, ResearchReport, Section } from "./schemas";

// ── Generic axis-pair shapes (4.2) ────────────────────────────────────

export interface PeerRowGeneric {
  symbol: string;
  x: number;
  y: number;
}

export interface MedianPointGeneric {
  x: number;
  y: number;
}

// ── Legacy (P/E × Gross Margin)-fixed shapes (3.3.C) ─────────────────

export interface PeerRow {
  symbol: string;
  pe: number;
  margin: number;
}

export interface MedianPoint {
  pe: number;
  margin: number;
}

export interface SubjectPoint {
  symbol: string;
  pe: number;
  margin: number;
}

// ── Backend ``_DESCRIPTIONS`` strings ────────────────────────────────

const PE_METRIC = "P/E ratio (trailing 12 months)";
const GROSS_MARGIN_METRIC = "Gross margin";

const MEDIAN_PE_DESC = `Peer median: ${PE_METRIC}`;
const MEDIAN_MARGIN_DESC = `Peer median: ${GROSS_MARGIN_METRIC}`;

// "<TICKER>: <metric_desc>" — anchored at start (^), TICKER is uppercase
// letters / digits / dot (BRK.B) / dash, then ": ", then the metric.
const PEER_CLAIM_RE = /^([A-Z][A-Z0-9.-]*): (.+)$/;

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

// ── 4.2 generic helpers ──────────────────────────────────────────────

/**
 * Group flat per-peer claims into one row per peer with both axis
 * metrics. Peers missing either metric drop out.
 *
 * ``xMetric`` / ``yMetric`` are the metric description strings (e.g.
 * ``"P/E ratio (trailing 12 months)"``). The function matches them
 * exactly against the ``"<TICKER>: <metric>"`` claim shape.
 */
export function groupPeersForAxes(
  claims: readonly Claim[],
  xMetric: string,
  yMetric: string,
): PeerRowGeneric[] {
  const byPeer = new Map<string, { x?: number; y?: number }>();

  for (const claim of claims) {
    const match = PEER_CLAIM_RE.exec(claim.description);
    if (!match) continue;
    const [, symbol, metric] = match;
    if (symbol === "Peer") continue;
    if (!isFiniteNumber(claim.value)) continue;

    if (metric === xMetric) {
      const row = byPeer.get(symbol) ?? {};
      row.x = claim.value;
      byPeer.set(symbol, row);
    } else if (metric === yMetric) {
      const row = byPeer.get(symbol) ?? {};
      row.y = claim.value;
      byPeer.set(symbol, row);
    }
  }

  const rows: PeerRowGeneric[] = [];
  for (const [symbol, { x, y }] of byPeer) {
    if (x === undefined || y === undefined) continue;
    rows.push({ symbol, x, y });
  }
  return rows;
}

/**
 * Pull the per-metric peer medians for the active axis pair. Returns
 * null when either median is missing or non-numeric.
 */
export function extractMedianForAxes(
  claims: readonly Claim[],
  xMetric: string,
  yMetric: string,
): MedianPointGeneric | null {
  const xDesc = `Peer median: ${xMetric}`;
  const yDesc = `Peer median: ${yMetric}`;
  let x: number | undefined;
  let y: number | undefined;
  for (const claim of claims) {
    if (claim.description === xDesc && isFiniteNumber(claim.value)) {
      x = claim.value;
    } else if (claim.description === yDesc && isFiniteNumber(claim.value)) {
      y = claim.value;
    }
  }
  if (x === undefined || y === undefined) return null;
  return { x, y };
}

// ── Legacy 3.3.C helpers — thin wrappers over the generic ones ───────

/**
 * Group flat per-peer claims into one row per peer with both P/E
 * and gross margin. Peers missing either metric drop out. Used by
 * the legacy 3.3.C PeerScatter; PeerScatterV2 calls
 * ``groupPeersForAxes`` directly.
 */
export function groupPeers(claims: readonly Claim[]): PeerRow[] {
  return groupPeersForAxes(claims, PE_METRIC, GROSS_MARGIN_METRIC).map(
    (r) => ({ symbol: r.symbol, pe: r.x, margin: r.y }),
  );
}

/**
 * Pull the per-metric peer medians (P/E + gross margin) for the
 * legacy reference dot. Returns null when either is missing.
 */
export function extractMedian(
  claims: readonly Claim[],
): MedianPoint | null {
  let pe: number | undefined;
  let margin: number | undefined;
  for (const claim of claims) {
    if (claim.description === MEDIAN_PE_DESC && isFiniteNumber(claim.value)) {
      pe = claim.value;
    } else if (
      claim.description === MEDIAN_MARGIN_DESC &&
      isFiniteNumber(claim.value)
    ) {
      margin = claim.value;
    }
  }
  if (pe === undefined || margin === undefined) return null;
  return { pe, margin };
}

function findSection(
  report: ResearchReport,
  title: string,
): Section | undefined {
  return report.sections.find((s) => s.title === title);
}

function findClaimValue(
  section: Section,
  description: string,
): number | null {
  const claim = section.claims.find((c) => c.description === description);
  if (!claim || !isFiniteNumber(claim.value)) return null;
  return claim.value;
}

/**
 * Cross-section join: subject's P/E from Valuation + gross margin
 * from Quality. Null when either section is absent (EARNINGS focus
 * mode skips Quality) or either value is non-numeric.
 */
export function extractSubject(
  report: ResearchReport,
): SubjectPoint | null {
  const valuation = findSection(report, "Valuation");
  const quality = findSection(report, "Quality");
  if (!valuation || !quality) return null;

  const pe = findClaimValue(valuation, PE_METRIC);
  const margin = findClaimValue(quality, GROSS_MARGIN_METRIC);
  if (pe === null || margin === null) return null;

  return { symbol: report.symbol, pe, margin };
}
