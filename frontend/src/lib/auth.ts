/**
 * Frontend auth helpers — single shared-secret bearer token kept in
 * localStorage. This is intentionally simple: one user (you), public
 * URL, light security gate. The backend dependency lives in
 * ``app/core/auth.py``; ADR 0004 captures the rationale.
 *
 * ## Why localStorage and not sessionStorage / cookies
 *
 * - sessionStorage drops on tab close — frustrating for a tool you
 *   open and re-open all day.
 * - Cookies require backend-side ``credentials: 'include'`` which
 *   conflicts with the explicit ``Authorization: Bearer`` header
 *   pattern (the backend doesn't read cookies, by design — see
 *   ``configure_cors`` which sets ``allow_credentials=False``).
 * - localStorage has well-known XSS exposure but our app has no
 *   third-party scripts and no user-generated HTML rendering, so
 *   the attack surface is small.
 *
 * ## Token rotation
 *
 * To rotate: ``fly secrets set BACKEND_SHARED_SECRET=<new>`` then
 * each user's first request 401s, the API client clears the bad
 * token, and they re-enter the new one at the login screen. There's
 * no list of who has the old token — a deliberate trade-off for
 * the simplicity of single-secret auth.
 */

const TOKEN_STORAGE_KEY = "market-agent.auth-token";

/** Read the token from localStorage. Returns null if not present. */
export function getStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    // localStorage can throw in private-mode Safari; treat as no-token.
    return null;
  }
}

/** Persist a token. Empty string clears (use ``clearStoredToken`` instead). */
export function setStoredToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    // Storage quota or private mode — silently no-op. The user will
    // get a re-login prompt on the next page load, which is fine.
  }
}

/** Forget the stored token. Called on 401 + on explicit logout. */
export function clearStoredToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    // see above
  }
}
