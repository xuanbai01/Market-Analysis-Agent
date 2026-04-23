import math

import pytest

from app.services.technicals import RSI_PERIOD, compute_technicals, rsi, sma

# ── SMA ───────────────────────────────────────────────────────────────

def test_sma_returns_mean_of_window() -> None:
    assert sma([1.0, 2.0, 3.0, 4.0, 5.0], period=3) == pytest.approx(4.0)


def test_sma_uses_most_recent_closes_not_oldest() -> None:
    # Oldest 100s must not bleed into the tail average.
    assert sma([100.0, 100.0, 100.0, 10.0, 20.0, 30.0], period=3) == pytest.approx(20.0)


def test_sma_none_when_insufficient_closes() -> None:
    assert sma([1.0, 2.0], period=3) is None
    assert sma([], period=1) is None


def test_sma_exact_boundary_returns_value() -> None:
    # Exactly `period` closes is enough; the boundary must not off-by-one.
    assert sma([1.0, 2.0, 3.0], period=3) == pytest.approx(2.0)


# ── RSI ───────────────────────────────────────────────────────────────

def test_rsi_pure_uptrend_returns_100() -> None:
    # period + 1 monotonically increasing closes → every change is a gain.
    closes = [float(i) for i in range(1, RSI_PERIOD + 2)]
    assert rsi(closes) == pytest.approx(100.0)


def test_rsi_pure_downtrend_returns_0() -> None:
    closes = [float(i) for i in range(RSI_PERIOD + 1, 0, -1)]
    assert rsi(closes) == pytest.approx(0.0)


def test_rsi_flat_returns_50_not_divide_by_zero() -> None:
    closes = [100.0] * (RSI_PERIOD + 1)
    assert rsi(closes) == pytest.approx(50.0)


def test_rsi_balanced_gains_and_losses_returns_50() -> None:
    # Alternating +1 / -1 changes over 14 periods sums to zero-ish gains=losses.
    closes = [100.0]
    for i in range(RSI_PERIOD):
        closes.append(closes[-1] + (1.0 if i % 2 == 0 else -1.0))
    # Two gains vs two losses of equal magnitude → RS=1 → RSI=50.
    value = rsi(closes)
    assert value is not None
    assert value == pytest.approx(50.0)


def test_rsi_none_when_insufficient_closes() -> None:
    # Need period + 1 closes for period price changes.
    assert rsi([1.0] * RSI_PERIOD) is None


def test_rsi_result_bounded_in_zero_hundred() -> None:
    # Random-ish walk, verify we never return NaN / out-of-range.
    closes = [100.0, 101, 99, 103, 98, 105, 97, 110, 95, 115, 90, 120, 88, 125, 85]
    value = rsi(closes)
    assert value is not None
    assert 0.0 <= value <= 100.0
    assert not math.isnan(value)


# ── compute_technicals bundling ──────────────────────────────────────

def test_compute_technicals_all_none_when_short_history() -> None:
    out = compute_technicals([100.0, 101.0, 102.0])
    assert out.rsi is None
    assert out.sma20 is None
    assert out.sma50 is None
    assert out.sma200 is None


def test_compute_technicals_fills_progressively_as_history_grows() -> None:
    # 20 closes: SMA20 ready, SMA50/200 and RSI(14) status vary.
    closes = [100.0 + i for i in range(20)]
    out = compute_technicals(closes)
    assert out.sma20 is not None
    assert out.sma50 is None
    assert out.sma200 is None
    assert out.rsi == pytest.approx(100.0)  # monotone up → saturated


def test_compute_technicals_full_history_populates_everything() -> None:
    closes = [100.0 + i for i in range(200)]
    out = compute_technicals(closes)
    assert out.sma20 is not None
    assert out.sma50 is not None
    assert out.sma200 is not None
    assert out.rsi is not None
