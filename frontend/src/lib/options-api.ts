/**
 * Fetchers for the options page (ADR 0008). Only the lazy options page
 * imports this module, so the options schemas stay out of the main chunk.
 */
import {
  ApiError,
  BACKEND_URL,
  authHeaders,
  extractErrorTitle,
  parseJsonAndValidate,
  parseRetryAfter,
} from "./api";
import {
  type ExpiryChain,
  ExpiryChainSchema,
  type OptionsRead,
  OptionsReadSchema,
  type OptionsReport,
  OptionsReportSchema,
} from "./options-schemas";

async function getJson<T>(path: string, parse: (resp: Response) => Promise<T>): Promise<T> {
  const resp = await fetch(`${BACKEND_URL}${path}`, { headers: { ...authHeaders() } });
  if (!resp.ok) {
    throw new ApiError({
      status: resp.status,
      title: await extractErrorTitle(resp),
      retryAfterSeconds: parseRetryAfter(resp.headers),
    });
  }
  return parse(resp);
}

/** Everything the page draws; built server-side in a couple of seconds, then cached 15 minutes. */
export function fetchOptionsReport(symbol: string): Promise<OptionsReport> {
  const ticker = encodeURIComponent(symbol.toUpperCase());
  return getJson(`/v1/options/${ticker}`, (resp) => parseJsonAndValidate(resp, OptionsReportSchema));
}

/** One expiry's smile, chain rows and open interest (``expiry`` is YYYY-MM-DD). */
export function fetchOptionsChain(symbol: string, expiry: string): Promise<ExpiryChain> {
  const ticker = encodeURIComponent(symbol.toUpperCase());
  return getJson(`/v1/options/${ticker}/chain/${encodeURIComponent(expiry)}`, (resp) =>
    parseJsonAndValidate(resp, ExpiryChainSchema),
  );
}

/** The cited AI read of the current report: written once per set of quotes. */
export function fetchOptionsRead(symbol: string): Promise<OptionsRead> {
  const ticker = encodeURIComponent(symbol.toUpperCase());
  return getJson(`/v1/options/${ticker}/read`, (resp) => parseJsonAndValidate(resp, OptionsReadSchema));
}
