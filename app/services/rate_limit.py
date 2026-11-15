"""
Per-key token-bucket rate limiter.

Each key (typically a client IP) gets its own bucket of ``capacity``
tokens that refills continuously at ``capacity / window_seconds``
tokens per second. Each ``take()`` consumes one token; if zero are
available, returns the seconds until the next token is ready.

Pure code — no FastAPI, no network. The FastAPI integration in
``app.api.v1.dependencies`` wraps ``take()`` and renders 429
problem+json on denial. A thin layer here keeps the logic testable
without spinning up an ASGI app or a fake clock at the request layer.

## In-memory only, single-process

Buckets live in a module-local dict keyed by IP. This is correct for
the current single-Fly-machine deployment; if we scale horizontally
later we'll need shared state (Redis, Cloudflare, etc.) and this
module becomes a thin adapter. Until then, no extra infra.

## Concurrency

A single ``asyncio.Lock`` serializes ``take()`` calls. Lock
contention is fine here because the critical section is tiny (read
+ refill math + write) and the rate-limited endpoint already pays
seconds of LLM latency per request — a microsecond of lock wait is
invisible.

## Time source

``time_source`` defaults to ``time.monotonic`` so DST changes and
clock jumps don't break refill math. Tests inject a callable that
returns a fixed value to simulate elapsed seconds without sleeping.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


class TokenBucket:
    """Rate-limit a stream of requests by key, using token-bucket math."""

    def __init__(
        self,
        *,
        capacity: int,
        window_seconds: float,
        time_source: Callable[[], float] = time.monotonic,
    ) -> None:
        if capacity < 0:
            raise ValueError(f"capacity must be >= 0, got {capacity}")
        if window_seconds <= 0:
            raise ValueError(
                f"window_seconds must be > 0, got {window_seconds}"
            )

        self._capacity = capacity
        self._window = window_seconds
        # Tokens-per-second refill rate. Zero when capacity=0; that's
        # the "deny everything" path documented in tests.
        self._refill_rate = (
            capacity / window_seconds if capacity > 0 else 0.0
        )
        self._time = time_source
        # key → (tokens_remaining, last_access_monotonic)
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = asyncio.Lock()
        self._pruned_at = float("-inf")

    # Past this many keys, a take() first drops the buckets that have
    # refilled: a full bucket holds no state, so memory follows recent
    # callers rather than every caller ever seen. At most once every
    # PRUNE_EVERY_SECONDS: with many keys none of which has refilled, a
    # scan on every take would cost each request the whole dict.
    PRUNE_AT = 1024
    PRUNE_EVERY_SECONDS = 30.0

    def _prune(self, now: float) -> None:
        full = [
            key for key, (tokens, last) in self._buckets.items()
            if tokens + (now - last) * self._refill_rate >= self._capacity
        ]
        for key in full:
            del self._buckets[key]

    async def give_back(self, key: str) -> None:
        """Return a token ``take`` took, for a request that turned out not
        to count. Never past capacity; a full bucket stores nothing."""
        async with self._lock:
            now = self._time()
            tokens, last = self._buckets.get(key, (float(self._capacity), now))
            tokens = tokens + (now - last) * self._refill_rate + 1.0
            if tokens >= self._capacity:
                self._buckets.pop(key, None)
            else:
                self._buckets[key] = (tokens, now)

    async def peek(self, key: str) -> tuple[bool, float]:
        """Whether a ``take`` for ``key`` would pass now, as ``(allowed,
        retry_after_seconds)``, without taking a token or storing a key."""
        async with self._lock:
            now = self._time()
            tokens, last = self._buckets.get(key, (float(self._capacity), now))
            tokens = min(float(self._capacity), tokens + (now - last) * self._refill_rate)
            if tokens >= 1.0:
                return True, 0.0
            if self._refill_rate <= 0:
                return False, float("inf")
            return False, (1.0 - tokens) / self._refill_rate

    async def take(self, key: str) -> tuple[bool, float]:
        """Try to consume one token for ``key``.

        Returns ``(allowed, retry_after_seconds)``. When ``allowed`` is
        True, ``retry_after_seconds`` is 0. When False, it's the
        seconds until one token will be available — caller surfaces
        that as an HTTP ``Retry-After`` header.
        """
        async with self._lock:
            now = self._time()
            if len(self._buckets) >= self.PRUNE_AT and now - self._pruned_at >= self.PRUNE_EVERY_SECONDS:
                self._prune(now)
                self._pruned_at = now
            tokens, last = self._buckets.get(
                key, (float(self._capacity), now)
            )

            # Continuous refill: add the tokens that accumulated since
            # we last touched this bucket, capped at capacity.
            elapsed = now - last
            tokens = min(
                float(self._capacity), tokens + elapsed * self._refill_rate
            )

            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                return True, 0.0

            # Not enough — leave the bucket as we found it (with the
            # refill applied) and tell the caller how long to wait.
            self._buckets[key] = (tokens, now)

            if self._refill_rate <= 0:
                # capacity=0 path: never refills; deny forever.
                return False, float("inf")
            seconds_until_one_token = (1.0 - tokens) / self._refill_rate
            return False, seconds_until_one_token
