"""
FastAPI dependencies.

- ``get_session`` yields an async SQLAlchemy session from the global
  ``SessionLocal``. The conftest test fixture overrides this to inject
  a per-test rolled-back session.
- ``enforce_research_rate_limit`` rate-limits ``/v1/research/*`` per
  client IP via the in-memory ``TokenBucket`` from
  ``app.services.rate_limit``. Disabled when
  ``RESEARCH_RATE_LIMIT_PER_HOUR=0``.

The rate-limit dependency lives here (as opposed to in the router) so
the router stays a thin coordinator and test setup can override the
bucket without touching the route handler.
"""
from __future__ import annotations

import math
from collections.abc import AsyncGenerator

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import settings
from app.db.session import SessionLocal
from app.services.rate_limit import TokenBucket


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


# Module-level singleton — single bucket shared across all requests in
# this process. Rate-limit state is per-IP inside the bucket; the
# singleton just amortizes the construction. Tests override via
# ``app.dependency_overrides``.
_RESEARCH_BUCKET: TokenBucket | None = None


def _get_research_bucket() -> TokenBucket | None:
    """Lazy-init the shared bucket. Returns None when rate limiting is off."""
    global _RESEARCH_BUCKET
    if settings.RESEARCH_RATE_LIMIT_PER_HOUR <= 0:
        return None
    if _RESEARCH_BUCKET is None:
        _RESEARCH_BUCKET = TokenBucket(
            capacity=settings.RESEARCH_RATE_LIMIT_PER_HOUR,
            window_seconds=3600.0,
        )
    return _RESEARCH_BUCKET


def _client_ip(request: Request) -> str:
    """Resolve the caller's IP, honoring X-Forwarded-For.

    Behind Fly's proxy (and any reverse proxy / load balancer in
    general), ``request.client.host`` is the proxy's IP, which would
    make every user share one bucket. The first entry of
    ``X-Forwarded-For`` is the originating client; later entries are
    intermediate hops.

    No spoofing protection here — Fly strips and re-sets XFF before
    requests reach us, so we trust it. Don't expose this app behind a
    proxy you don't control without revisiting.
    """
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    # Local test ASGI transport may not set client; treat as one bucket.
    return "unknown"


async def enforce_research_rate_limit(request: Request) -> None:
    """Per-IP rate limit for /v1/research/*. 429 with Retry-After on deny."""
    bucket = _get_research_bucket()
    if bucket is None:
        return  # rate limiting disabled

    key = _client_ip(request)
    allowed, retry_after = await bucket.take(key)
    if allowed:
        return

    # Render Retry-After as integer seconds (RFC 7231 prefers
    # delta-seconds; ``inf`` from a capacity=0 bucket caps at a sane
    # year so HTTP libraries don't choke).
    retry_int = (
        31_536_000  # 1 year
        if math.isinf(retry_after)
        else max(1, int(math.ceil(retry_after)))
    )
    raise HTTPException(
        status_code=429,
        detail=(
            f"Rate limit exceeded: "
            f"{settings.RESEARCH_RATE_LIMIT_PER_HOUR}/hour per IP. "
            f"Retry in ~{retry_int} seconds."
        ),
        headers={"Retry-After": str(retry_int)},
    )


def reset_research_rate_limit_for_tests() -> None:
    """Drop the module-level bucket so tests start with fresh state.

    Production code never calls this — it would defeat the rate limit.
    Test fixtures that mutate ``RESEARCH_RATE_LIMIT_PER_HOUR`` invoke
    it so the next request rebuilds the bucket with the new capacity.
    """
    global _RESEARCH_BUCKET
    _RESEARCH_BUCKET = None
