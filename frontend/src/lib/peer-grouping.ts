/**
 * peer-grouping — pure helpers for the Peers section's PeerScatter.
 * Phase 3.3.C.
 *
 * Three responsibilities, each a pure function with no React /
 * recharts coupling so they can be tested in isolation:
 *
 * 1. ``groupPeers(claims)`` — parses the flat ``Claim[]`` emitted by
 *    ``app/services/peers.py`` (descriptions of the form
 *    ``"<TICKER>: <metric_desc>"``) into ``{symbol, pe, margin}``
 *    rows. One row per peer; peers missing either metric drop out.
 *
 * 2. ``extractMedian(claims)`` — pulls the per-metric medians (those
 *    have descriptions ``"Peer median: <metric_desc>"``) so the
 *    scatter can render a faint reference dot.
 *
 * 3. ``extractSubject(report)`` — cross-section join: the report's
 *    own symbol P/E lives in the Valuation section
 *    (``"P/E ratio (trailing 12 months)"``) and gross margin in the
 *    Quality section (``"Gross margin"``). Returns null when either
 *    section is missing (e.g. EARNINGS focus mode skips Quality) or
 *    either value is non-numeric.
 *
 * ## Why descriptions, not keys
 *
 * Same reason as ``featured-claim`` (Phase 3.3.B): the Pydantic schema
 * flattens ``dict[str, Claim]`` into ``Section.claims: list[Claim]``
 * and the stable backend keys (``AMD.trailing_pe``, …) don't survive.
 * Descriptions are stable strings defined in
 * ``app/services/peers.py::_DESCRIPTIONS`` and
 * ``app/services/fundamentals.py::_DESCRIPTIONS``; tests pin them so
 * a backend rename fails loudly.
 */
import type { Claim, ResearchReport, Section } from "./schemas";

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

// Backend ``_DESCRIPTIONS`` strings — copy-paste from the source of
// truth in app/services/peers.py + app/services/fundamentals.py.
// Defined as constants so the test file imports them directly if
// needed.
const PE_METRIC_SUFFIX = "P/E ratio (trailing 12 months)";
const GROSS_MARGIN_METRIC = "Gross margin";

const MEDIAN_PE_DESC = `Peer median: ${PE_METRIC_SUFFIX}`;
const MEDIAN_MARGIN_DESC = `Peer median: ${GROSS_MARGIN_METRIC}`;

// "<TICKER>: <metric_desc>" — anchored at start (^), TICKER is
// uppercase letters / digits / dot (BRK.B) / dash, then ": ", then
// the metric desc. The matcher only fires for descriptions that
// look like a peer claim; sector / peers_list / median.* miss this
// shape.
const PEER_CLAIM_RE = /^([A-Z][A-Z0-9.-]*): (.+)$/;

function isFiniteNumber(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/**
 * Group flat per-peer claims into one row per peer with both P/E
 * and gross margin. Peers missing either metric drop out.
 */
export function groupPeers(claims: readonly Claim[]): PeerRow[] {
  const byPeer = new Map<string, { pe?: number; margin?: number }>();

  for (const claim of claims) {
    const match = PEER_CLAIM_RE.exec(claim.description);
    if (!match) continue;
    const [, symbol, metric] = match;

    // Skip the median.* claims — they match the regex
    // ("Peer: median: ...") via the "Peer" capture, but the metric
    // half starts with "median:" which isn't one of the two we want.
    // Cheaper: explicitly exclude here even though the match against
    // the metric desc below would already filter them.
    if (symbol === "Peer") continue;

    if (metric === PE_METRIC_SUFFIX && isFiniteNumber(claim.value)) {
      const row = byPeer.get(symbol) ?? {};
      row.pe = claim.value;
      byPeer.set(symbol, row);
    } else if (metric === GROSS_MARGIN_METRIC && isFiniteNumber(claim.value)) {
      const row = byPeer.get(symbol) ?? {};
      row.margin = claim.value;
      byPeer.set(symbol, row);
    }
  }

  const rows: PeerRow[] = [];
  for (const [symbol, { pe, margin }] of byPeer) {
    if (pe === undefined || margin === undefined) continue;
    rows.push({ symbol, pe, margin });
  }
  return rows;
}

/**
 * Pull the per-metric peer medians for the reference dot. Returns
 * null when either median is missing or non-numeric.
 */
export function extractMedian(claims: readonly Claim[]): MedianPoint | null {
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

  const pe = findClaimValue(valuation, PE_METRIC_SUFFIX);
  const margin = findClaimValue(quality, GROSS_MARGIN_METRIC);
  if (pe === null || margin === null) return null;

  return { symbol: report.symbol, pe, margin };
}
