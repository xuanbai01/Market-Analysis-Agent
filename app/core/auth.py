"""
Shared-secret bearer auth for protected routes (Phase 3.0).

The frontend (Phase 3.1) is going to live on a public Vercel URL hitting
the public Fly URL. Without an auth gate, anyone discovering the
backend hostname could drain rate-limit tokens (or, worse, fill up the
Anthropic bill). This module provides one FastAPI dependency,
``require_shared_secret``, mounted on ``/v1/research/*`` to gate that
surface.

## Operating modes

The auth dep is a no-op when ``settings.BACKEND_SHARED_SECRET`` is
empty (the default). This keeps local dev and the existing test suite
working without rewiring every test to send a token. Production sets
the secret via ``fly secrets set BACKEND_SHARED_SECRET=...``.

When set, the dep enforces ``Authorization: Bearer <secret>``. The
comparison is constant-time (``hmac.compare_digest``) so a timing
adversary can't probe the secret byte by byte. Scheme matching is
case-insensitive (RFC 7235 §2.1), but the token itself is compared
strictly — leading whitespace, trailing whitespace, or any difference
all 401.

## Why a single shared secret, not per-user auth

Phase 3 ships with one user (you) and a "let trusted friends try it"
public-link goal. Real auth (Clerk, magic-link via Resend, Auth0)
costs 1–2 days of work and real ongoing complexity for zero
multi-user benefit today. The dep boundary is cleanly extractable:
when multi-user lands, replace this single dep with a token-validating
one and the rest of the app doesn't notice. ADR 0004 captures the
trade-off and the trigger for revisiting.

## What this dep does NOT do

- It does not rate-limit. ``enforce_research_rate_limit`` is separate.
  Auth and rate limiting compose: protected routes check auth first
  (cheap), then rate-limit on cache miss (after the cache lookup, see
  ``app/api/v1/routers/research.py``).
- It does not log auth failures with the offending token. We log the
  IP and the failure mode, but never the token itself — that would
  defeat the point of redacting credentials in observability output.
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from app.core.settings import settings

_BEARER_SCHEME = "bearer"
# WWW-Authenticate header on 401 — RFC 7235 §3.1 recommends this so
# clients know how to retry. ``realm`` is informational; the value is
# not validated by anything.
_WWW_AUTHENTICATE = 'Bearer realm="market-agent"'


async def require_shared_secret(
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """Gate a route on ``Authorization: Bearer <BACKEND_SHARED_SECRET>``.

    No-op when ``BACKEND_SHARED_SECRET`` is empty (dev / test default).
    Otherwise:

    - Missing or malformed header → 401 + ``WWW-Authenticate: Bearer``.
    - Wrong scheme → 401.
    - Wrong secret → 401 (constant-time compare).
    - Right secret → return None (FastAPI lets the request through).
    """
    expected = settings.BACKEND_SHARED_SECRET
    if not expected:
        return  # auth disabled

    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail="Missing Authorization header.",
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )

    # Split exactly once on the first whitespace. ``"Bearer  token"``
    # (two spaces) intentionally lands token=" token" which fails
    # compare_digest — we keep this strict so clients construct the
    # header the obvious way.
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != _BEARER_SCHEME or not token:
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header. Expected: Bearer <token>.",
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )

    if not hmac.compare_digest(token, expected):
        raise HTTPException(
            status_code=401,
            detail="Invalid token.",
            headers={"WWW-Authenticate": _WWW_AUTHENTICATE},
        )
