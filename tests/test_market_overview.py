"""
The market strip service + route (app/services/market_overview.py).

yfinance is replaced by a fake ``fetch_closes`` that records calls, so
these tests pin quote building, caching and failure handling without
the network.
"""
from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import date, timedelta
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core import settings as settings_module
from app.main import app
from app.services import market_overview as mo

FRIDAY = date(2026, 11, 6)


def _closes(values: list[float], end: date = FRIDAY) -> list[tuple[date, float]]:
    start = end - timedelta(days=len(values) - 1)
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def _calm(base: float, n: int = 420) -> list[float]:
    return [base * (1 + 0.02 * ((i % 10) - 4.5) / 4.5) for i in range(n)]


class FakeYahoo:
    """Stands in for yf.download: canned closes per symbol, counts calls."""

    def __init__(self, data: dict[str, list[tuple[date, float]]], fail: bool = False) -> None:
        self.data = data
        self.fail = fail
        self.calls: list[tuple[tuple[str, ...], str, bool]] = []

    def __call__(self, symbols: Sequence[str], period: str, adjusted: bool) -> dict[str, Any]:
        self.calls.append((tuple(symbols), period, adjusted))
        if self.fail:
            raise RuntimeError("Yahoo is down")
        return {s: self.data[s] for s in symbols if s in self.data}


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    mo.clear_cache()


def _market() -> dict[str, list[tuple[date, float]]]:
    return {
        "^GSPC": _closes(_calm(6700)[:-2] + [6800.0, 6732.0]),
        "^NDX": _closes([24000.0, 24240.0]),
        "^VIX": _closes(_calm(16)[:-2] + [16.0, 20.0]),
        "^TNX": _closes([4.837, 4.859]),
        "BTC-USD": _closes([75747.58, 75165.73], end=FRIDAY + timedelta(days=2)),
        "IEF": _closes(_calm(95)),
        "HYG": _closes(_calm(80)),
    }


def test_build_quote_compares_the_last_two_closes() -> None:
    spec = mo.QuoteSpec("^GSPC", "S&P 500", "index", "points")
    q = mo.build_quote(spec, _closes([6800.0, 6732.0]))
    assert q is not None
    assert q.price == 6732.0
    assert q.change == pytest.approx(-68.0)
    assert q.change_percent == pytest.approx(-1.0)
    assert q.as_of == FRIDAY
    assert mo.build_quote(spec, _closes([6732.0])) is None


async def test_overview_lists_quotes_in_strip_order_and_skips_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mo, "fetch_closes", FakeYahoo(_market()))
    overview = await mo.get_market_overview()
    assert [q.symbol for q in overview.quotes] == ["^GSPC", "^NDX", "^VIX", "^TNX", "BTC-USD"]
    tnx = next(q for q in overview.quotes if q.symbol == "^TNX")
    assert tnx.unit == "percent" and tnx.kind == "rate"
    btc = next(q for q in overview.quotes if q.symbol == "BTC-USD")
    assert btc.as_of == FRIDAY + timedelta(days=2)  # trades on weekends


async def test_overview_includes_the_sentiment_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeYahoo(_market())
    monkeypatch.setattr(mo, "fetch_closes", fake)
    overview = await mo.get_market_overview()
    assert overview.sentiment is not None
    assert len(overview.sentiment.components) == 4
    # Quotes use raw closes over a short window; sentiment uses
    # dividend-adjusted closes over two years.
    by_period = {period: adjusted for _symbols, period, adjusted in fake.calls}
    assert by_period == {mo.QUOTES_PERIOD: False, mo.SENTIMENT_PERIOD: True}


async def test_overview_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeYahoo(_market())
    monkeypatch.setattr(mo, "fetch_closes", fake)
    await mo.get_market_overview()
    await mo.get_market_overview()
    assert len(fake.calls) == 2  # one quotes + one sentiment download, total


async def test_expired_cache_refetches(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeYahoo(_market())
    monkeypatch.setattr(mo, "fetch_closes", fake)
    clock = [1000.0]
    monkeypatch.setattr(mo, "monotonic", lambda: clock[0])
    await mo.get_market_overview()
    clock[0] += mo.QUOTES_TTL_SECONDS + 1
    await mo.get_market_overview()
    periods = [period for _s, period, _a in fake.calls]
    assert periods.count(mo.QUOTES_PERIOD) == 2
    assert periods.count(mo.SENTIMENT_PERIOD) == 1  # still within its hour


async def test_failed_refresh_serves_the_last_good_value(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeYahoo(_market())
    monkeypatch.setattr(mo, "fetch_closes", fake)
    clock = [1000.0]
    monkeypatch.setattr(mo, "monotonic", lambda: clock[0])
    first = await mo.get_market_overview()
    fake.fail = True
    clock[0] += mo.SENTIMENT_TTL_SECONDS + 1
    again = await mo.get_market_overview()
    assert again.quotes == first.quotes
    assert again.sentiment == first.sentiment


async def test_provider_down_with_nothing_cached_is_empty_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mo, "fetch_closes", FakeYahoo({}, fail=True))
    overview = await mo.get_market_overview()
    assert overview.quotes == []
    assert overview.sentiment is None


async def test_empty_result_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeYahoo({})
    monkeypatch.setattr(mo, "fetch_closes", fake)
    await mo.get_market_overview()
    fake.data = _market()
    overview = await mo.get_market_overview()
    assert overview.quotes  # retried instead of serving a cached empty strip


@pytest_asyncio.fixture
async def api(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncClient]:
    monkeypatch.setattr(mo, "fetch_closes", FakeYahoo(_market()))
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", "")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


async def test_route_returns_the_overview(api: AsyncClient) -> None:
    resp = await api.get("/v1/market/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["quotes"][0] == {
        "symbol": "^GSPC",
        "label": "S&P 500",
        "kind": "index",
        "unit": "points",
        "price": 6732.0,
        "change": pytest.approx(-68.0),
        "change_percent": pytest.approx(-1.0),
        "as_of": "2026-11-06",
    }
    assert body["sentiment"]["rating"] in {"extreme_fear", "fear", "neutral", "greed", "extreme_greed"}
    assert "generated_at" in body
