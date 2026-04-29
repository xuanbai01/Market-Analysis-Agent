"""
Tests for ``app.services.rate_limit.TokenBucket``.

Pure-code unit tests — no FastAPI, no network, no clock. The bucket
takes an injectable ``time_source`` so we can fake elapsed time
deterministically. Real wall-clock behavior is validated separately
via the router integration tests in ``tests/test_research_router.py``.
"""
from __future__ import annotations

import pytest

from app.services.rate_limit import TokenBucket


class _FakeClock:
    """Monotonic clock that only advances when the test says so."""

    def __init__(self, start: float = 0.0) -> None:
        self._t = start

    def __call__(self) -> float:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += seconds


# ── Bucket basics ────────────────────────────────────────────────────


async def test_first_request_for_new_key_is_allowed() -> None:
    """A fresh key starts with a full bucket."""
    clock = _FakeClock()
    bucket = TokenBucket(capacity=3, window_seconds=3600, time_source=clock)

    allowed, retry = await bucket.take("ip-A")

    assert allowed is True
    assert retry == 0.0


async def test_capacity_calls_in_a_row_all_allowed() -> None:
    """N requests within the window all succeed; the (N+1)th is denied."""
    clock = _FakeClock()
    bucket = TokenBucket(capacity=3, window_seconds=3600, time_source=clock)

    for i in range(3):
        allowed, _ = await bucket.take("ip-A")
        assert allowed is True, f"request {i} should have been allowed"

    allowed, retry = await bucket.take("ip-A")
    assert allowed is False
    assert retry > 0


async def test_denied_request_returns_retry_after_seconds() -> None:
    """Retry-After is the seconds until 1 token regenerates."""
    clock = _FakeClock()
    bucket = TokenBucket(capacity=3, window_seconds=3600, time_source=clock)

    # Drain the bucket.
    for _ in range(3):
        await bucket.take("ip-A")

    allowed, retry = await bucket.take("ip-A")
    assert allowed is False
    # 3 tokens / 3600s = 1 token / 1200s. With 0 tokens left, we need
    # 1200s of wall-clock to get one back.
    assert retry == pytest.approx(1200.0, rel=0.01)


# ── Refill ───────────────────────────────────────────────────────────


async def test_refill_after_window_elapses_allows_again() -> None:
    """Wait the full window and the bucket is back to capacity."""
    clock = _FakeClock()
    bucket = TokenBucket(capacity=3, window_seconds=3600, time_source=clock)

    for _ in range(3):
        await bucket.take("ip-A")

    # Just past the next refill point.
    clock.advance(1201)

    allowed, _ = await bucket.take("ip-A")
    assert allowed is True


async def test_partial_refill_during_window() -> None:
    """Halfway through the window, half the capacity is back."""
    clock = _FakeClock()
    bucket = TokenBucket(capacity=4, window_seconds=3600, time_source=clock)

    # Drain.
    for _ in range(4):
        await bucket.take("ip-A")
    allowed, _ = await bucket.take("ip-A")
    assert allowed is False

    # Advance half the window — should restore 2 tokens.
    clock.advance(1800)

    # Two requests should now succeed; the third should not.
    assert (await bucket.take("ip-A"))[0] is True
    assert (await bucket.take("ip-A"))[0] is True
    assert (await bucket.take("ip-A"))[0] is False


async def test_refill_caps_at_capacity() -> None:
    """A bucket idle for many windows doesn't exceed capacity."""
    clock = _FakeClock()
    bucket = TokenBucket(capacity=3, window_seconds=3600, time_source=clock)

    # Take one to register the bucket.
    await bucket.take("ip-A")
    # Advance way past the window.
    clock.advance(10_000_000)

    # Capacity remains 3 — only 3 calls in a row succeed, not more.
    for _ in range(3):
        assert (await bucket.take("ip-A"))[0] is True
    assert (await bucket.take("ip-A"))[0] is False


# ── Per-key isolation ────────────────────────────────────────────────


async def test_different_keys_have_independent_buckets() -> None:
    """ip-A draining its bucket must not affect ip-B."""
    clock = _FakeClock()
    bucket = TokenBucket(capacity=2, window_seconds=3600, time_source=clock)

    for _ in range(2):
        assert (await bucket.take("ip-A"))[0] is True
    assert (await bucket.take("ip-A"))[0] is False

    # ip-B has its own full bucket.
    for _ in range(2):
        assert (await bucket.take("ip-B"))[0] is True
    assert (await bucket.take("ip-B"))[0] is False


async def test_unknown_key_starts_full() -> None:
    """A bucket can be drained for one key while many others remain full."""
    clock = _FakeClock()
    bucket = TokenBucket(capacity=1, window_seconds=3600, time_source=clock)

    for ip in ("ip-A", "ip-B", "ip-C", "ip-D"):
        allowed, _ = await bucket.take(ip)
        assert allowed is True


# ── Capacity edge cases ───────────────────────────────────────────────


async def test_capacity_one_means_strict_serialization() -> None:
    """capacity=1: one request, then denied until refill."""
    clock = _FakeClock()
    bucket = TokenBucket(capacity=1, window_seconds=3600, time_source=clock)

    assert (await bucket.take("ip-A"))[0] is True
    assert (await bucket.take("ip-A"))[0] is False

    clock.advance(3601)
    assert (await bucket.take("ip-A"))[0] is True


async def test_capacity_zero_denies_all_requests() -> None:
    """capacity=0 makes the bucket reject everything.

    The dependency layer treats ``RESEARCH_RATE_LIMIT_PER_HOUR=0`` as
    "disabled" and never instantiates a bucket. But if a test or
    operator does instantiate ``TokenBucket(capacity=0)``, the
    contract is "deny everything cleanly" — not crash, not allow.
    """
    clock = _FakeClock()
    bucket = TokenBucket(capacity=0, window_seconds=3600, time_source=clock)

    allowed, retry = await bucket.take("ip-A")
    assert allowed is False
    # Refill rate is 0, so retry-after is infinite. We return inf
    # rather than crash — caller can decide how to render it.
    assert retry == float("inf")


# ── Validation ───────────────────────────────────────────────────────


async def test_negative_capacity_raises() -> None:
    """Negative capacity is a programming error; fail loud at construction."""
    with pytest.raises(ValueError, match="capacity"):
        TokenBucket(capacity=-1, window_seconds=3600)


async def test_zero_or_negative_window_raises() -> None:
    """Window must be a positive duration."""
    with pytest.raises(ValueError, match="window_seconds"):
        TokenBucket(capacity=3, window_seconds=0)
    with pytest.raises(ValueError, match="window_seconds"):
        TokenBucket(capacity=3, window_seconds=-100)
