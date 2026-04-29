/**
 * Login screen — single password field + "unlock" button.
 *
 * The flow:
 *
 * 1. User pastes the shared secret.
 * 2. We probe with ``GET /v1/research?limit=1`` — cheap, idempotent,
 *    doesn't burn a rate-limit token.
 * 3. On 200, persist the token and call ``onAuthenticated()`` so
 *    ``App`` swaps to the dashboard.
 * 4. On 401, show "Wrong password" inline; keep the field's value so
 *    the user can correct a typo without retyping the whole secret.
 * 5. On any other error (network, CORS, 5xx), show the message
 *    verbatim — usually that means the backend isn't reachable.
 *
 * No "remember me" toggle: a public URL with an unauthenticated user
 * is the design. If you don't want to be remembered, close the tab.
 */
import { useState, type FormEvent } from "react";
import { ApiError, probeAuth } from "../lib/api";
import { setStoredToken } from "../lib/auth";

interface Props {
  onAuthenticated: () => void;
}

export function LoginScreen({ onAuthenticated }: Props) {
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!secret) return;

    setError(null);
    setSubmitting(true);
    try {
      const ok = await probeAuth(secret);
      if (!ok) {
        setError("Wrong password.");
        return;
      }
      setStoredToken(secret);
      onAuthenticated();
    } catch (err) {
      // Network or unexpected error. ApiError carries a useful title;
      // anything else is rendered verbatim.
      const message =
        err instanceof ApiError
          ? err.title
          : err instanceof Error
            ? err.message
            : "Could not reach the backend.";
      setError(message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center bg-slate-50 p-6">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div>
          <h1 className="text-xl font-semibold text-slate-900">
            Market Analysis Agent
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Enter your access password to continue.
          </p>
        </div>

        <label className="block">
          <span className="text-sm font-medium text-slate-700">Password</span>
          <input
            type="password"
            autoFocus
            autoComplete="current-password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            disabled={isSubmitting}
            className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm shadow-sm focus:border-slate-500 focus:outline-none focus:ring-1 focus:ring-slate-500 disabled:bg-slate-100"
            placeholder="Shared secret"
            aria-invalid={error !== null}
            aria-describedby={error ? "login-error" : undefined}
          />
        </label>

        {error && (
          <p id="login-error" className="text-sm text-red-600" role="alert">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={isSubmitting || !secret}
          className="w-full rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {isSubmitting ? "Checking…" : "Unlock"}
        </button>
      </form>
    </div>
  );
}
