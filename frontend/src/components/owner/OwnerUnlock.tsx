/**
 * The owner key's unlock form (ADR 0009, amended). A fixed, hidden username
 * names the key, so Chrome, Edge, Bitwarden or 1Password save it and sync
 * it to the owner's other PCs; it posts, so a stray native submit can't put
 * the key in a URL. The key is checked against the server before it's kept.
 */
import { type FormEvent, useState } from "react";

import { ApiError } from "../../lib/api";
import { setOwnerKey } from "../../lib/owner";
import { fetchOwnerStatus } from "../../lib/owner-api";

export const OWNER_USERNAME = "market-agent-owner";

function refusal(err: unknown): string {
  if (!(err instanceof ApiError)) return "Couldn't reach the server.";
  if (err.status === 403) return "That isn't the owner key.";
  if (err.status === 404) return "The server has no owner key yet: set one with docs/deployment.md §10.";
  if (err.status === 429) {
    const minutes = err.retryAfterSeconds ? Math.max(1, Math.ceil(err.retryAfterSeconds / 60)) : null;
    return `Too many wrong keys from this address${minutes ? `: try again in about ${minutes} minute${minutes === 1 ? "" : "s"}` : ""}.`;
  }
  if (err.status === 401) return "Your sign-in has expired: sign in again first.";
  return err.title;
}

export function OwnerUnlock({ onUnlocked }: { onUnlocked?: () => void }) {
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!key) return;
    setError(null);
    setChecking(true);
    try {
      await fetchOwnerStatus(key);
      setOwnerKey(key);
      onUnlocked?.();
    } catch (err) {
      setError(refusal(err));
    } finally {
      setChecking(false);
    }
  }

  return (
    <form
      method="post"
      onSubmit={submit}
      data-testid="owner-unlock"
      className="mx-auto mt-10 w-full max-w-sm space-y-4 rounded-lg border border-strata-border bg-strata-surface p-6"
    >
      <div>
        <h1 className="text-lg font-semibold text-strata-hi">Your account</h1>
        <p className="mt-1 text-sm text-strata-dim">
          Your positions and trades need the owner key, on top of your sign-in. Your password manager can keep it for each of your PCs.
        </p>
      </div>
      <input type="text" name="username" autoComplete="username" value={OWNER_USERNAME} readOnly hidden />
      <label className="block">
        <span className="text-sm font-medium text-strata-fg">Owner key</span>
        <input
          type="password"
          name="password"
          autoFocus
          autoComplete="current-password"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          disabled={checking}
          aria-invalid={error !== null}
          aria-describedby={error ? "owner-unlock-error" : undefined}
          className="mt-1 block w-full rounded-md border border-strata-border bg-strata-raise px-3 py-2 text-sm text-strata-hi focus:border-strata-highlight focus:outline-none focus:ring-1 focus:ring-strata-highlight"
        />
      </label>
      {error && (
        <p id="owner-unlock-error" role="alert" className="text-sm text-strata-neg">
          {error}
        </p>
      )}
      <button
        type="submit"
        disabled={checking || !key}
        className="w-full rounded-md bg-strata-highlight px-3 py-2 text-sm font-medium text-strata-canvas hover:bg-strata-highlight/90 disabled:cursor-not-allowed disabled:bg-strata-muted disabled:text-strata-dim"
      >
        {checking ? "Checking…" : "Unlock"}
      </button>
    </form>
  );
}
