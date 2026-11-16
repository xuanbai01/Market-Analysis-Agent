"""The owner's IV history from tastytrade (ADR 0009, PR C).

tastytrade's daily candles carry the stock's IV (a fraction) from about
2016, and its market metrics give today's IV index, IV rank and
percentile (fractions) and the 30-day IV and historical volatilities
(percent; checked on Fly, 2026-11-16, without printing a value). Kept in
memory only, behind the owner key, never stored, never in a prompt.
tastytrade and DXLink are faked here.
"""
from __future__ import annotations

import asyncio
import logging
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
    # Today against the year's other sessions: the high is above all of them.
    assert year.iv_rank == pytest.approx(1.0) and year.iv_percentile == pytest.approx(1.0)
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


# ── from #138's reviews ─────────────────────────────────────────────────


async def test_the_year_is_the_last_year_of_sessions_not_of_ivs(account: _Tastytrade) -> None:
    # Sparse IVs mustn't stretch "the past year" over several.
    account.candles = _candles(600, iv=lambda i: 0.3 if i < 300 or i % 10 == 0 else None)
    year = (await ih.iv_history("NVDA")).year
    assert year.sessions == 25  # the IVs among the last 252 sessions (every tenth of 348-599)


async def test_metrics_missing_with_candles_present_is_a_history(account: _Tastytrade) -> None:
    account.metrics = []
    history = await ih.iv_history("NVDA")
    assert history.points and history.metrics.iv_rank is None


async def test_a_symbol_tastytrade_doesnt_know_for_metrics_lets_the_candles_decide(
    account: _Tastytrade, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def not_found(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise tt.TastytradeNotFound("/market-metrics")

    monkeypatch.setattr(ih.tt, "get", not_found)
    assert (await ih.iv_history("NVDA")).points
    account.candles = dxlink.CandleHistory(candles=(), complete=True)
    ih.reset()
    with pytest.raises(ih.NoHistory):
        await ih.iv_history("NVDA")


@pytest.mark.parametrize("payload", [[1, 2], {"data": "x"}, {"data": {"items": 5}}, {"data": {"items": ["x"]}}])
async def test_a_wrong_shaped_metrics_answer_reads_as_none(
    account: _Tastytrade, monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    async def odd(*args: Any, **kwargs: Any) -> Any:
        return payload

    monkeypatch.setattr(ih.tt, "get", odd)
    history = await ih.iv_history("NVDA")
    assert history.points and history.metrics.iv_index is None


async def test_the_metrics_echoed_in_another_class_share_form_still_match(account: _Tastytrade) -> None:
    account.metrics[0]["symbol"] = "BRK.B"
    assert (await ih.iv_history("BRK-B")).metrics.iv_index == pytest.approx(0.4123)


async def test_a_failed_metrics_call_stops_the_candle_fetch(
    account: _Tastytrade, monkeypatch: pytest.MonkeyPatch
) -> None:
    stopped = []

    async def slow_candles(*args: Any) -> dxlink.CandleHistory:
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            stopped.append(True)
            raise
        return account.candles

    monkeypatch.setattr(ih.dxlink, "fetch_candles", slow_candles)
    account.fail = tt.TastytradeUnavailable("tastytrade answered 503")
    with pytest.raises(ih.IvHistoryUnavailable):
        await ih.iv_history("NVDA")
    assert stopped == [True]


async def test_an_expired_history_is_dropped_on_any_visit(account: _Tastytrade) -> None:
    await ih.iv_history("NVDA")
    account.clock[0] += ih.CACHE_SECONDS + 1  # type: ignore[attr-defined]
    account.fail = tt.TastytradeUnavailable("down")
    with pytest.raises(ih.IvHistoryUnavailable):
        await ih.iv_history("SPY")  # no build kept, yet NVDA's expired copy goes
    assert "NVDA" not in ih._kept


async def test_candles_outside_the_window_are_left_out(account: _Tastytrade) -> None:
    # tastytrade sent everything when it misread fromTime (dxlink): keep ten years.
    old = dxlink.Candle(time=datetime(1999, 1, 4, tzinfo=UTC), open=1, high=1, low=1, close=1.0, volume=1,
                        imp_volatility=0.3, open_interest=None)
    future = dxlink.Candle(time=NOW + timedelta(days=3), open=1, high=1, low=1, close=1.0, volume=1,
                           imp_volatility=0.3, open_interest=None)
    account.candles = dxlink.CandleHistory(candles=(old, *_candles(50).candles, future), complete=True)
    points = (await ih.iv_history("NVDA")).points
    assert len(points) == 50 and points[0].date.year == 2026


@pytest.mark.parametrize("symbol", ["SPY,QQQ", "X{=d}", "", "toolongticker", "A/B/C"])
async def test_the_service_checks_the_symbol_itself(account: _Tastytrade, symbol: str) -> None:
    # The route's pattern is the first check; a later caller mustn't put a
    # list or dxFeed's attribute syntax into tastytrade's query.
    with pytest.raises(ih.NoHistory):
        await ih.iv_history(symbol)
    assert account.calls == [] and account.candle_asks == []


async def test_two_forms_of_one_share_class_share_a_copy(account: _Tastytrade) -> None:
    await ih.iv_history("BRK-B")
    await ih.iv_history("BRK.B")
    assert len(account.candle_asks) == 1


async def test_a_close_that_isnt_a_price_is_no_close(account: _Tastytrade) -> None:
    candles = list(_candles(30).candles)
    candles[-1] = dxlink.Candle(time=candles[-1].time, open=0, high=0, low=0, close=0.0, volume=0,
                                imp_volatility=0.3, open_interest=None)
    account.candles = dxlink.CandleHistory(candles=tuple(candles), complete=True)
    assert (await ih.iv_history("NVDA")).points[-1].close is None


async def test_a_deadline_hit_is_logged_without_the_symbol(
    account: _Tastytrade, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def stuck(*args: Any) -> dxlink.CandleHistory:
        await asyncio.sleep(10)
        return account.candles

    monkeypatch.setattr(ih.dxlink, "fetch_candles", stuck)
    monkeypatch.setattr(ih, "BUILD_SECONDS", 0.05)
    with caplog.at_level(logging.WARNING, logger="app"), pytest.raises(ih.IvHistoryUnavailable):
        await ih.iv_history("ZQXW")
    messages = [r.getMessage() for r in caplog.records if r.name.startswith("app")]
    assert any("gave up" in m for m in messages) and not any("ZQXW" in m for m in messages)


def test_a_timestamp_comes_back_in_utc() -> None:
    assert ih.metrics_of({"implied-volatility-updated-at": "2026-11-14T15:59:00-05:00"}).updated_at == datetime(
        2026, 11, 14, 20, 59, tzinfo=UTC)
