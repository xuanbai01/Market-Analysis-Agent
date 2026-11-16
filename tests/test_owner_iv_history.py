"""The owner's IV history from tastytrade (ADR 0009, PR C).

tastytrade's daily candles carry the stock's IV (a fraction) from about
2016, and its market metrics give today's IV index, IV rank and
percentile (fractions) and the 30-day IV and historical volatilities
(percent; checked on Fly, 2026-11-16, without printing a value). Kept in
memory only, behind the owner key, never stored, never in a prompt.
tastytrade and DXLink are faked here.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.v1 import dependencies as deps
from app.core import settings as settings_module
from app.main import app
from app.services import dxlink
from app.services import options_math as om
from app.services import owner_iv_history as ih
from app.services import tastytrade_client as tt

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)
OWNER_KEY = "o" * 40  # plainly fake


def _sessions(n: int, last: date = date(2026, 11, 13)) -> list[date]:
    days: list[date] = []
    day = last
    while len(days) < n:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    return days[::-1]


def _candles(n: int = 400, iv: Any = None) -> dxlink.CandleHistory:
    """Closes on a gentle zigzag; IV rising from 20% to about 40%."""
    out = []
    for i, day in enumerate(_sessions(n)):
        close = 100 * (1.01 if i % 2 else 0.99) * (1 + i / 1000)
        vol = (0.20 + 0.20 * i / n) if iv is None else iv(i)
        out.append(dxlink.Candle(time=datetime(day.year, day.month, day.day, tzinfo=UTC), open=close, high=close,
                                 low=close, close=close, volume=1e6, imp_volatility=vol, open_interest=None))
    return dxlink.CandleHistory(candles=tuple(out), complete=True)


METRICS = {
    "symbol": "NVDA",
    "implied-volatility-index": "0.4123",
    "implied-volatility-30-day": "41.5",
    "tw-implied-volatility-index-rank": "0.62",
    "implied-volatility-percentile": "0.71",
    "historical-volatility-30-day": "35.2",
    "historical-volatility-60-day": "38.0",
    "historical-volatility-90-day": "40.1",
    "implied-volatility-updated-at": "2026-11-14T20:59:00.000+00:00",
}


class _Tastytrade:
    def __init__(self) -> None:
        self.metrics: list[dict[str, Any]] = [dict(METRICS)]
        self.candles = _candles()
        self.calls: list[str] = []
        self.candle_asks: list[tuple[str, str, datetime]] = []
        self.fail: Exception | None = None
        self.candle_fail: Exception | None = None

    async def get(self, path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        self.calls.append(path)
        if self.fail:
            raise self.fail
        assert path == "/market-metrics" and params is not None and "symbols" in params
        return {"data": {"items": self.metrics}}

    async def fetch_candles(self, symbol: str, period: str, from_time: datetime) -> dxlink.CandleHistory:
        self.candle_asks.append((symbol, period, from_time))
        if self.candle_fail:
            raise self.candle_fail
        return self.candles


@pytest.fixture
def account(monkeypatch: pytest.MonkeyPatch) -> _Tastytrade:
    fake = _Tastytrade()
    monkeypatch.setattr(ih.tt, "get", fake.get)
    monkeypatch.setattr(ih.tt, "is_configured", lambda: True)
    monkeypatch.setattr(ih.dxlink, "fetch_candles", fake.fetch_candles)
    monkeypatch.setattr(ih, "_now", lambda: NOW)
    clock = [1000.0]
    monkeypatch.setattr(ih, "_clock", lambda: clock[0])
    fake.clock = clock  # type: ignore[attr-defined]
    ih.reset()
    yield fake
    ih.reset()


# ── today's figures ─────────────────────────────────────────────────────


async def test_tastytrade_s_figures_come_as_fractions(account: _Tastytrade) -> None:
    m = (await ih.iv_history("NVDA")).metrics
    assert m.iv_index == pytest.approx(0.4123) and m.iv30 == pytest.approx(0.415)  # percent read as a fraction
    assert m.iv_rank == pytest.approx(0.62) and m.iv_percentile == pytest.approx(0.71)
    assert (m.hv30, m.hv60, m.hv90) == pytest.approx((0.352, 0.38, 0.401))
    assert m.updated_at == datetime(2026, 11, 14, 20, 59, tzinfo=UTC)


@pytest.mark.parametrize(
    ("name", "sent"),
    [("implied-volatility-index", "45"), ("implied-volatility-index", "-0.1"), ("implied-volatility-30-day", "900"),
     ("tw-implied-volatility-index-rank", "62"), ("implied-volatility-percentile", "1.5"),
     ("historical-volatility-30-day", "NaN"), ("implied-volatility-index", None)],
)
async def test_a_figure_out_of_its_range_is_no_figure(account: _Tastytrade, name: str, sent: Any) -> None:
    # A unit tastytrade changed would otherwise show as 4,500% IV.
    account.metrics[0][name] = sent
    m = (await ih.iv_history("NVDA")).metrics
    field = {"implied-volatility-index": "iv_index", "implied-volatility-30-day": "iv30",
             "tw-implied-volatility-index-rank": "iv_rank", "implied-volatility-percentile": "iv_percentile",
             "historical-volatility-30-day": "hv30"}[name]
    assert getattr(m, field) is None


# ── the history ─────────────────────────────────────────────────────────


async def test_each_session_has_its_close_iv_and_realized_volatility(account: _Tastytrade) -> None:
    history = await ih.iv_history("NVDA")
    points = history.points
    assert len(points) == 400 and points[0].date < points[-1].date
    assert points[-1].date == date(2026, 11, 13)  # the candle's own UTC date is the session
    closes = [c.close for c in account.candles.candles]
    assert all(p.rv20 is None for p in points[: ih.RV_WINDOW])
    assert points[-1].rv20 == pytest.approx(om.realized_vol(closes, ih.RV_WINDOW), rel=1e-4)
    assert points[-1].iv == pytest.approx(0.20 + 0.20 * 399 / 400, rel=1e-4)
    assert history.iv_since == points[0].date and history.complete is True


async def test_candles_are_asked_for_ten_years_of_sessions(account: _Tastytrade) -> None:
    await ih.iv_history("BRK-B")
    symbol, period, since = account.candle_asks[0]
    assert (symbol, period) == ("BRK/B", "d")  # tastytrade's form of a class share
    assert NOW - since >= timedelta(days=365 * ih.YEARS)


async def test_an_iv_that_cant_be_a_fraction_is_left_out(account: _Tastytrade) -> None:
    account.candles = _candles(60, iv=lambda i: [0.3, 35.0, float("nan"), None, -0.2][i % 5])
    points = (await ih.iv_history("NVDA")).points
    assert [p.iv for p in points[:5]] == [0.3, None, None, None, None]


async def test_where_today_sits_in_the_past_year(account: _Tastytrade) -> None:
    # IV rising steadily: today's is the year's high.
    year = (await ih.iv_history("NVDA")).year
    assert year.sessions == ih.YEAR_SESSIONS
    assert year.iv_high == pytest.approx(0.20 + 0.20 * 399 / 400, rel=1e-4)
    assert year.iv_rank == pytest.approx(1.0) and year.iv_percentile == pytest.approx(251 / 252, rel=1e-4)
    assert year.iv_low < year.iv_median < year.iv_high


async def test_a_short_history_says_how_short(account: _Tastytrade) -> None:
    account.candles = _candles(30)
    year = (await ih.iv_history("NVDA")).year
    assert year.sessions == 30


async def test_a_flat_year_has_no_rank(account: _Tastytrade) -> None:
    account.candles = _candles(300, iv=lambda i: 0.25)
    year = (await ih.iv_history("NVDA")).year
    assert year.iv_rank is None and year.iv_percentile == 0.0


async def test_figures_are_rounded_to_keep_the_answer_small(account: _Tastytrade) -> None:
    point = (await ih.iv_history("NVDA")).points[-1]
    for value in (point.close, point.iv, point.rv20):
        assert value is not None and round(value, ih.DIGITS) == value


# ── failures, the cache ─────────────────────────────────────────────────


async def test_a_symbol_tastytrade_has_nothing_for_is_said_so(account: _Tastytrade) -> None:
    account.metrics = []
    account.candles = dxlink.CandleHistory(candles=(), complete=True)
    with pytest.raises(ih.NoHistory):
        await ih.iv_history("ZZZZ")


async def test_tastytrade_failing_is_said_with_the_reason(account: _Tastytrade) -> None:
    account.fail = tt.TastytradeUnavailable("tastytrade answered 503")
    with pytest.raises(ih.IvHistoryUnavailable, match="503"):
        await ih.iv_history("NVDA")


async def test_the_feed_failing_is_said_with_the_reason(account: _Tastytrade) -> None:
    account.candle_fail = dxlink.DxlinkError("the feed refused the subscription")
    with pytest.raises(ih.IvHistoryUnavailable, match="feed"):
        await ih.iv_history("NVDA")


async def test_without_tastytrade_it_says_why(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ih.tt, "is_configured", lambda: False)
    with pytest.raises(ih.IvHistoryUnavailable, match="isn't set up"):
        await ih.iv_history("NVDA")


async def test_a_second_look_within_the_cache_asks_nothing(account: _Tastytrade) -> None:
    await ih.iv_history("NVDA")
    await ih.iv_history("NVDA")
    assert len(account.candle_asks) == 1
    account.clock[0] += ih.CACHE_SECONDS + 1  # type: ignore[attr-defined]
    await ih.iv_history("NVDA")
    assert len(account.candle_asks) == 2


async def test_only_the_last_few_symbols_are_kept(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ih, "MAX_SYMBOLS", 2)
    for symbol in ("A", "B", "C"):
        await ih.iv_history(symbol)
    assert list(ih._kept) == ["B", "C"]


async def test_a_failed_build_is_not_kept(account: _Tastytrade) -> None:
    account.candle_fail = dxlink.DxlinkError("dropped")
    with pytest.raises(ih.IvHistoryUnavailable):
        await ih.iv_history("NVDA")
    account.candle_fail = None
    assert (await ih.iv_history("NVDA")).points


# ── the route ───────────────────────────────────────────────────────────


async def _get(path: str, headers: dict[str, str]) -> Any:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


@pytest.fixture
def owner(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", "")
    monkeypatch.setattr(settings_module.settings, "OWNER_KEY", SecretStr(OWNER_KEY))
    deps.reset_owner_failures_for_tests()
    return {deps.OWNER_HEADER: OWNER_KEY}


async def test_the_route_serves_the_history_to_the_owner_only(account: _Tastytrade, owner: dict[str, str]) -> None:
    path = "/v1/owner/options/nvda/history"
    assert (await _get(path, {})).status_code == 403
    resp = await _get(path, owner)
    assert resp.status_code == 200 and resp.headers["Cache-Control"] == "no-store"
    body = resp.json()
    assert body["symbol"] == "NVDA" and body["source"] == "tastytrade" and len(body["points"]) == 400
    for bad in ("not!a!ticker", "A-B-C", "A."):
        assert (await _get(f"/v1/owner/options/{bad}/history", owner)).status_code == 422, bad


async def test_no_history_is_a_422_not_a_404(account: _Tastytrade, owner: dict[str, str]) -> None:
    # The page reads a 404 from an owner route as "no owner key".
    account.metrics = []
    account.candles = dxlink.CandleHistory(candles=(), complete=True)
    resp = await _get("/v1/owner/options/ZZZZ/history", owner)
    assert resp.status_code == 422 and "no IV history" in resp.json()["title"]


async def test_the_route_is_a_503_with_the_reason(account: _Tastytrade, owner: dict[str, str]) -> None:
    account.fail = tt.TastytradeUnavailable("tastytrade answered 503")
    resp = await _get("/v1/owner/options/NVDA/history", owner)
    assert resp.status_code == 503 and "503" in resp.json()["title"]


def test_the_history_is_never_written_to_the_database() -> None:
    # ADR 0009: tastytrade's data is never stored. The module has no session.
    with open(ih.__file__, encoding="utf-8") as fh:
        source = fh.read()
    assert "AsyncSession" not in source and "SessionLocal" not in source
