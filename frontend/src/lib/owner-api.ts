/**
 * Fetchers for the owner's routes (ADR 0009, amended): the shared secret
 * plus ``X-Owner-Key``. Only the lazy owner pages import this. Answers are
 * never cached by the browser (``no-store`` both ways).
 */
import { ApiError, BACKEND_URL, authHeaders, extractErrorTitle, parseJsonAndValidate, parseRetryAfter } from "./api";
import { type OwnerPositions, OwnerPositionsSchema, type OwnerStatus, OwnerStatusSchema } from "./owner-schemas";

export const OWNER_HEADER = "X-Owner-Key";

async function ownerGet<T>(path: string, key: string, parse: (resp: Response) => Promise<T>): Promise<T> {
  const resp = await fetch(`${BACKEND_URL}${path}`, {
    headers: { ...authHeaders(), [OWNER_HEADER]: key },
    cache: "no-store",
    // A redirect would carry the custom header to wherever it points.
    redirect: "error",
  });
  if (!resp.ok) {
    throw new ApiError({
      status: resp.status,
      title: await extractErrorTitle(resp),
      retryAfterSeconds: parseRetryAfter(resp.headers),
    });
  }
  return parse(resp);
}

/** A 200 says the key is right; it also says whether tastytrade is set up. */
export function fetchOwnerStatus(key: string): Promise<OwnerStatus> {
  return ownerGet("/v1/owner/status", key, (resp) => parseJsonAndValidate(resp, OwnerStatusSchema));
}

/** The owner's positions with tastytrade's live quotes, at most 15 s old. */
export function fetchOwnerPositions(key: string): Promise<OwnerPositions> {
  return ownerGet("/v1/owner/positions", key, (resp) => parseJsonAndValidate(resp, OwnerPositionsSchema));
}

/** The server refused the owner key (wrong, or none configured there). */
export function isOwnerKeyRefused(error: unknown): boolean {
  return error instanceof ApiError && (error.status === 403 || error.status === 404);
}
