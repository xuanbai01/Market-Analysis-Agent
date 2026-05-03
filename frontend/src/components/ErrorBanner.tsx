/**
 * Error banner with status-code-aware messaging.
 *
 * The backend surfaces three meaningful failure modes for the
 * research endpoint:
 *
 * - 401 — auth gate rejected the token. We render a generic "session
 *   expired" message; the App component is also responsible for
 *   clearing the bad token + bouncing back to login.
 * - 429 — rate limited. Show the Retry-After header so the user knows
 *   how long to wait.
 * - 503 — synth dependency unavailable (usually ANTHROPIC_API_KEY
 *   missing on the backend). Show the title verbatim — it's
 *   actionable.
 *
 * Anything else falls through to a generic banner.
 */
import { ApiError } from "../lib/api";

interface Props {
  error: unknown;
  onDismiss?: () => void;
}

export function ErrorBanner({ error, onDismiss }: Props) {
  let title = "Something went wrong.";
  let detail: string | null = null;

  if (error instanceof ApiError) {
    if (error.status === 429) {
      title = "Rate limit reached.";
      detail =
        error.retryAfterSeconds !== undefined
          ? `Try again in about ${error.retryAfterSeconds} second${error.retryAfterSeconds === 1 ? "" : "s"}.`
          : "Please wait a bit before retrying.";
    } else if (error.status === 401) {
      title = "Session expired.";
      detail = "Please re-enter the access password.";
    } else if (error.status === 503) {
      title = "Synthesis unavailable.";
      detail = error.title;
    } else if (error.status === 502) {
      title = "Unexpected response from the backend.";
      detail = error.title;
    } else {
      title = `Error ${error.status}`;
      detail = error.title;
    }
  } else if (error instanceof Error) {
    detail = error.message;
  }

  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-3 rounded-md border border-strata-neg/40 bg-strata-neg/10 p-4 text-sm text-strata-neg"
    >
      <div>
        <p className="font-medium">{title}</p>
        {detail && <p className="mt-1 text-strata-neg/80">{detail}</p>}
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="rounded p-1 text-strata-neg hover:bg-strata-neg/15"
          aria-label="Dismiss"
        >
          ×
        </button>
      )}
    </div>
  );
}
