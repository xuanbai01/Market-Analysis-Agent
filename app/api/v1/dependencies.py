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

import ipaddress
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
    """The caller's IP, the key for every per-IP limit.

    Behind Fly's proxy ``request.client.host`` is the proxy, which would
    put every caller in one bucket. Fly sets ``Fly-Client-IP`` to the
    address it accepted the connection from, replacing any value a client
    sends; ``X-Forwarded-For`` it only appends to, keeping whatever the
    client wrote first, so keying on that let a caller mint a new bucket
    per request (security review, #114). A value that isn't an IP is
    ignored, so a key is always a short, real address. Off Fly (local,
    tests) the socket's peer.
    """
    fly = request.headers.get("fly-client-ip")
    if fly:
        try:
            return str(ipaddress.ip_address(fly.strip()))
        except ValueError:
            pass
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


_DEMO_BUCKET: TokenBucket | None = None


async def enforce_demo_rate_limit(request: Request) -> None:
    """Per-IP rate limit for the open ``/v1/demo`` routes. They serve
    cached bytes, so the limit is there to stop one caller crowding out
    the rest. 429 with Retry-After on deny; 0 disables it."""
    global _DEMO_BUCKET
    per_minute = settings.DEMO_RATE_LIMIT_PER_MINUTE
    if per_minute <= 0:
        return
    if _DEMO_BUCKET is None:
        _DEMO_BUCKET = TokenBucket(capacity=per_minute, window_seconds=60.0)
    allowed, retry_after = await _DEMO_BUCKET.take(_client_ip(request))
    if allowed:
        return
    retry_int = 60 if math.isinf(retry_after) else max(1, int(math.ceil(retry_after)))
    raise HTTPException(
        status_code=429,
        detail=f"Too many requests. Retry in ~{retry_int} seconds.",
        headers={"Retry-After": str(retry_int)},
    )


# Per-IP hourly buckets for the options routes, one per kind of cost.
_OPTIONS_BUCKETS: dict[str, TokenBucket] = {}


async def _enforce_hourly(kind: str, per_hour: int, request: Request, what: str) -> None:
    """Take one from ``kind``'s bucket for this IP; 429 with Retry-After
    when it's empty. 0 per hour disables the limit."""
    if per_hour <= 0:
        return
    bucket = _OPTIONS_BUCKETS.get(kind)
    if bucket is None:
        bucket = _OPTIONS_BUCKETS[kind] = TokenBucket(capacity=per_hour, window_seconds=3600.0)
    allowed, retry_after = await bucket.take(_client_ip(request))
    if allowed:
        return
    retry_int = 3600 if math.isinf(retry_after) else max(1, int(math.ceil(retry_after)))
    raise HTTPException(
        status_code=429,
        detail=f"Too many {what}: {per_hour}/hour per IP. Retry in ~{retry_int} seconds.",
        headers={"Retry-After": str(retry_int)},
    )


async def enforce_options_rate_limit(request: Request) -> None:
    """Per-IP limit on options page builds (the route calls it only on a
    cache miss): each is about a dozen Yahoo calls."""
    await _enforce_hourly("build", settings.OPTIONS_RATE_LIMIT_PER_HOUR, request, "option lookups")


async def enforce_options_read_rate_limit(request: Request) -> None:
    """Per-IP limit on cited reads the model has to write (the route calls
    it only when no read of the same quotes is cached)."""
    await _enforce_hourly("read", settings.OPTIONS_READ_RATE_LIMIT_PER_HOUR, request, "option reads")


def reset_options_rate_limit_for_tests() -> None:
    """Drop the options buckets so the next request rebuilds them (tests only)."""
    _OPTIONS_BUCKETS.clear()


def reset_demo_rate_limit_for_tests() -> None:
    """Drop the demo bucket so the next request rebuilds it (tests only)."""
    global _DEMO_BUCKET
    _DEMO_BUCKET = None


def reset_research_rate_limit_for_tests() -> None:
    """Drop the module-level bucket so tests start with fresh state.

    Production code never calls this — it would defeat the rate limit.
    Test fixtures that mutate ``RESEARCH_RATE_LIMIT_PER_HOUR`` invoke
    it so the next request rebuilds the bucket with the new capacity.
    """
    global _RESEARCH_BUCKET
    _RESEARCH_BUCKET = None
