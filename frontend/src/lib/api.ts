/**
 * Thin fetch wrapper for the backend.
 *
 * Responsibilities:
 *
 * - Inject the bearer token from ``localStorage`` on every request.
 * - Map backend error responses (RFC 7807 problem+json from
 *   ``app/core/errors.py``) into a typed ``ApiError`` we can switch
 *   on in the UI (401 → re-login, 429 → retry-after banner, 503 →
 *   "synth unavailable", anything else → generic).
 * - Validate response shapes via Zod so a backend drift fails loudly
 *   here, not three components deep.
 *
 * This is the only module that calls ``fetch`` directly. Components
 * use TanStack Query hooks that wrap these functions.
 */
import { z } from "zod";
import { getStoredToken } from "./auth";
import {
  type Focus,
  type MarketPrices,
  type ResearchReport,
  type ResearchReportSummary,
  MarketPricesSchema,
  ResearchReportSchema,
  ResearchReportSummariesSchema,
} from "./schemas";

// VITE_BACKEND_URL is injected at build time. Default to localhost
// for ``npm run dev`` against a local FastAPI on :8000. Strip a
// trailing slash so we don't end up with double-slashes when joining
// paths.
const RAW_BASE_URL = import.meta.env.VITE_BACKEND_URL ?? "http://localhost:8000";
export const BACKEND_URL = RAW_BASE_URL.replace(/\/+$/, "");

// ── Error model ──────────────────────────────────────────────────────

export interface ApiErrorShape {
  status: number;
  title: string;
  /** Seconds the server asked us to wait before retrying (429). */
  retryAfterSeconds?: number;
}

export class ApiError extends Error implements ApiErrorShape {
  status: number;
  title: string;
  retryAfterSeconds?: number;

  constructor(opts: ApiErrorShape) {
    super(opts.title);
    this.name = "ApiError";
    this.status = opts.status;
    this.title = opts.title;
    this.retryAfterSeconds = opts.retryAfterSeconds;
  }
}

// ── Internal helpers ─────────────────────────────────────────────────

function authHeaders(): Record<string, string> {
  const token = getStoredToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** Read ``Retry-After`` as integer seconds, or undefined. */
function parseRetryAfter(headers: Headers): number | undefined {
  const raw = headers.get("Retry-After");
  if (!raw) return undefined;
  const n = parseInt(raw, 10);
  return Number.isFinite(n) && n >= 0 ? n : undefined;
}

/** Pull a useful error message out of an RFC 7807 (or vanilla JSON) body. */
async function extractErrorTitle(resp: Response): Promise<string> {
  try {
    const body = (await resp.json()) as { title?: string; detail?: unknown };
    if (typeof body.title === "string" && body.title.length > 0) {
      return body.title;
    }
    if (typeof body.detail === "string" && body.detail.length > 0) {
      return body.detail;
    }
  } catch {
    // body wasn't JSON; fall through
  }
  return resp.statusText || `HTTP ${resp.status}`;
}

async function parseJsonAndValidate<S extends z.ZodTypeAny>(
  resp: Response,
  schema: S,
): Promise<z.output<S>> {
  // Generic over the schema (not its inferred type) so callers always
  // get the OUTPUT type — i.e. with Zod's ``.default(...)`` already
  // applied. Going via ``z.ZodType<T>`` would give us the INPUT type
  // and lose the defaults at the type level.
  const json = (await resp.json()) as unknown;
  const parsed = schema.safeParse(json);
  if (!parsed.success) {
    // Backend drift (or our schema is stale). Surface as a 502-shaped
    // error so the UI shows it as "upstream returned something
    // unexpected" rather than crashing on undefined.
    throw new ApiError({
      status: 502,
      title: `Response shape mismatch: ${parsed.error.message.slice(0, 200)}`,
    });
  }
  return parsed.data;
}

// ── Public API ───────────────────────────────────────────────────────

/**
 * Probe the auth gate with a candidate token. Returns true if the
 * server accepts it. Used by the login screen so the user knows
 * whether their secret is right BEFORE we persist it.
 *
 * Implementation: ``GET /v1/research?limit=1``. Cheap (single
 * indexed SELECT), idempotent, doesn't consume a rate-limit token.
 */
export async function probeAuth(candidateToken: string): Promise<boolean> {
  const resp = await fetch(`${BACKEND_URL}/v1/research?limit=1`, {
    method: "GET",
    headers: { Authorization: `Bearer ${candidateToken}` },
  });
  return resp.ok;
}

/**
 * Generate (or re-serve) a research report.
 *
 * - Cache hit: ~10ms, no rate-limit token spent.
 * - Cache miss: ~30s + one rate-limit token.
 * - ``refresh: true``: forces a fresh synth, spends a token.
 */
export async function fetchResearchReport(
  symbol: string,
  opts: { focus?: Focus; refresh?: boolean } = {},
): Promise<ResearchReport> {
  const params = new URLSearchParams();
  if (opts.focus) params.set("focus", opts.focus);
  if (opts.refresh) params.set("refresh", "true");
  const query = params.toString();
  const url =
    `${BACKEND_URL}/v1/research/${encodeURIComponent(symbol.toUpperCase())}` +
    (query ? `?${query}` : "");

  const resp = await fetch(url, {
    method: "POST",
    headers: { ...authHeaders() },
  });

  if (!resp.ok) {
    throw new ApiError({
      status: resp.status,
      title: await extractErrorTitle(resp),
      retryAfterSeconds: parseRetryAfter(resp.headers),
    });
  }
  return parseJsonAndValidate(resp, ResearchReportSchema);
}

/** List past reports, newest-first, for the dashboard sidebar. */
export async function listResearchReports(
  opts: { limit?: number; offset?: number; symbol?: string } = {},
): Promise<ResearchReportSummary[]> {
  const params = new URLSearchParams();
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.symbol) params.set("symbol", opts.symbol);
  const query = params.toString();
  const url = `${BACKEND_URL}/v1/research${query ? `?${query}` : ""}`;

  const resp = await fetch(url, {
    method: "GET",
    headers: { ...authHeaders() },
  });

  if (!resp.ok) {
    throw new ApiError({
      status: resp.status,
      title: await extractErrorTitle(resp),
    });
  }
  return parseJsonAndValidate(resp, ResearchReportSummariesSchema);
}

/**
 * Phase 4.1 — daily-bar OHLCV for the hero price chart.
 *
 * `range` is one of "60D" / "1Y" / "5Y" matching the backend's
 * accepted values. The backend reads through the `candles` cache,
 * falling back to yfinance ingestion on miss.
 */
export async function fetchMarketPrices(
  ticker: string,
  range: string,
): Promise<MarketPrices> {
  const url = `${BACKEND_URL}/v1/market/${encodeURIComponent(
    ticker.toUpperCase(),
  )}/prices?range=${encodeURIComponent(range)}`;

  const resp = await fetch(url, {
    method: "GET",
    headers: { ...authHeaders() },
  });

  if (!resp.ok) {
    throw new ApiError({
      status: resp.status,
      title: await extractErrorTitle(resp),
    });
  }
  return parseJsonAndValidate(resp, MarketPricesSchema);
}
