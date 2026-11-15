"""The options page's service (ADR 0008): the real build, with Yahoo, the
earnings schedule and the store faked."""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from app.services import options_report as orp
from app.services.earnings_calendar import Schedule
from app.services.options_chain import ChainFetch, SymbolNotFound
from tests.test_options_metrics import DIVIDEND, EXP_20, EXP_48, QUOTED_AT, SPOT, _chain, _flat

NOW = datetime(2026, 11, 14, 17, tzinfo=UTC)  # Saturday: quotes are Friday's close
EXP_FAR = date(2027, 6, 18)
CLOSES = tuple((date(2026, 8, 1) + timedelta(days=i), 100.0 + (i % 3)) for i in range(100))


class _Yahoo:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.broken = False
        self.skip: set[date] = set()
        self.listed = (EXP_20, EXP_48)

    def fetch_chain(self, symbol: str, pick: Any, *, history_period: str = "6mo", provider: str = "yfinance") -> Any:
        self.calls.append(symbol)
        if symbol == "ZZZZQ":
            raise SymbolNotFound(symbol)
        if symbol == "BRK-A":
            return None
        if self.broken:
            raise RuntimeError("yahoo down")
        chosen = [d for d in pick(self.listed, {"quoteType": "EQUITY"}) if d not in self.skip]
        return ChainFetch(
            symbol=symbol, spot=SPOT, market_time=int(QUOTED_AT.timestamp()), dividend_yield=DIVIDEND,
            expiries=self.listed, chains={d: _chain(d, _flat(0.25)) for d in chosen}, closes=CLOSES,
            name="Test Co", quote_type="EQUITY",
        )


class _Store:
    def __init__(self) -> None:
        self.points: list[tuple[date, float]] = []
        self.touched: list[str] = []

    async def iv30_history(self, _session: Any, symbol: str, _version: int) -> list[tuple[date, float]]:
        return list(self.points)

    async def touch_tracked(self, _session: Any, symbol: str, _at: datetime) -> None:
        self.touched.append(symbol)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> tuple[_Yahoo, _Store, list[float]]:
    yahoo, store, clock = _Yahoo(), _Store(), [0.0]
    orp.clear_cache()
    monkeypatch.setattr(orp.options_chain, "fetch_chain", yahoo.fetch_chain)
    monkeypatch.setattr(orp.options_chain, "risk_free_rate", lambda: (0.04, False))
    monkeypatch.setattr(orp.earnings_calendar, "fetch_schedule", lambda _s: Schedule(next=None, past=()))
    monkeypatch.setattr(orp.store, "iv30_history", store.iv30_history)
    monkeypatch.setattr(orp.store, "touch_tracked", store.touch_tracked)
    monkeypatch.setattr(orp, "_clock", lambda: clock[0])
    yield yahoo, store, clock
    orp.clear_cache()


async def _report(symbol: str = "TEST") -> Any:
    return await orp.get_report(None, symbol, now=NOW)  # type: ignore[arg-type]


async def test_a_report_from_a_chain(world: Any) -> None:
    report = await _report()
    assert report.status == "ok" and report.name == "Test Co"
    assert report.iv30 == pytest.approx(0.25, abs=1e-4)
    assert [e.expiry for e in report.expiries] == [EXP_20, EXP_48]
    assert report.chain is not None and report.chain.expiry == EXP_20
    assert report.listed_expiries == [EXP_20, EXP_48]
    assert report.quoted_at == QUOTED_AT
    assert any(c.description.startswith("Implied volatility, 30 days") for c in report.claims)
    assert report.earnings is not None and report.earnings.refused == "no earnings date"


async def test_the_report_is_cached_for_15_minutes(world: Any) -> None:
    yahoo, _store, clock = world
    await _report()
    clock[0] = orp.CACHE_TTL_SECONDS - 1
    await _report()
    assert yahoo.calls == ["TEST"]
    assert orp.is_fresh("TEST")
    clock[0] = orp.CACHE_TTL_SECONDS + 1
    assert not orp.is_fresh("TEST")
    await _report()
    assert yahoo.calls == ["TEST", "TEST"]


async def test_a_view_is_recorded_only_for_a_usable_report(world: Any) -> None:
    _yahoo, store, _clock = world
    await _report()
    no_options = await _report("BRK-A")
    assert no_options.status == "no_options" and no_options.expiries == []
    assert store.touched == ["TEST"]


async def test_no_options_is_cached_for_hours(world: Any) -> None:
    yahoo, _store, clock = world
    await _report("BRK-A")
    clock[0] = 3600.0
    await _report("BRK-A")
    assert yahoo.calls == ["BRK-A"]


async def test_an_unknown_symbol_raises_and_is_not_cached(world: Any) -> None:
    yahoo, _store, _clock = world
    for _ in range(2):
        with pytest.raises(SymbolNotFound):
            await _report("ZZZZQ")
    assert yahoo.calls == ["ZZZZQ", "ZZZZQ"]


async def test_a_failed_rebuild_serves_the_stale_copy(world: Any) -> None:
    yahoo, _store, clock = world
    first = await _report()
    clock[0] = orp.CACHE_TTL_SECONDS + 1
    yahoo.broken = True
    assert await _report() == first


async def test_a_failure_with_nothing_cached_raises(world: Any) -> None:
    yahoo, _store, _clock = world
    yahoo.broken = True
    with pytest.raises(RuntimeError):
        await _report()


async def test_concurrent_requests_share_one_fetch(world: Any) -> None:
    yahoo, _store, _clock = world
    await asyncio.gather(_report(), _report(), _report())
    assert yahoo.calls == ["TEST"]


async def test_the_stored_history_ranks_todays_iv30(world: Any) -> None:
    _yahoo, store, _clock = world
    store.points = [(date(2026, 1, 1) + timedelta(days=i), 0.10 + 0.002 * i) for i in range(70)]
    report = await _report()
    assert report.history.sessions == 70
    assert report.history.percentile is not None and report.history.rank is None


async def test_a_cached_expiry_is_served_without_a_fetch(world: Any) -> None:
    yahoo, _store, _clock = world
    await _report()
    chain = await orp.get_chain(None, "TEST", EXP_48, now=NOW)  # type: ignore[arg-type]
    assert chain.expiry == EXP_48 and chain.rows
    assert yahoo.calls == ["TEST"]


async def test_an_expiry_yahoo_does_not_list_is_refused(world: Any) -> None:
    with pytest.raises(orp.ExpiryNotListed):
        await orp.get_chain(None, "TEST", date(2027, 3, 19), now=NOW)  # type: ignore[arg-type]


async def test_a_listed_expiry_not_read_yet_costs_one_fetch(world: Any) -> None:
    yahoo, _store, _clock = world
    yahoo.listed = (EXP_20, EXP_48, EXP_FAR)
    yahoo.skip = {EXP_FAR}
    await _report()
    yahoo.skip = set()
    chain = await orp.get_chain(None, "TEST", EXP_FAR, now=NOW)  # type: ignore[arg-type]
    assert chain.expiry == EXP_FAR
    assert yahoo.calls == ["TEST", "TEST"]


async def test_an_expiry_that_failed_is_not_fetched_again(world: Any) -> None:
    """DeepSeek on PR 110: every request for it cost three Yahoo calls."""
    yahoo, _store, _clock = world
    yahoo.listed = (EXP_20, EXP_48, EXP_FAR)
    yahoo.skip = {EXP_FAR}
    await _report()
    for _ in range(2):
        with pytest.raises(orp.NoUsableQuotes):
            await orp.get_chain(None, "TEST", EXP_FAR, now=NOW)  # type: ignore[arg-type]
    assert yahoo.calls == ["TEST", "TEST"]
    # Both answer without Yahoo now: EXP_FAR is known to have nothing to price.
    assert orp.has_chain("TEST", EXP_20) and orp.has_chain("TEST", EXP_FAR)


async def test_a_database_failure_still_serves_the_report(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """DeepSeek on PR 110: a history read failing after a good build threw
    the build away (a 503). The history is optional; the report isn't."""
    async def broken(*_a: Any) -> Any:
        raise ConnectionError("database gone")

    monkeypatch.setattr(orp.store, "iv30_history", broken)
    monkeypatch.setattr(orp.store, "touch_tracked", broken)
    report = await _report()
    assert report.status == "ok" and report.history.sessions == 0


async def test_a_symbol_that_fails_leaves_no_lock_behind(world: Any) -> None:
    with pytest.raises(SymbolNotFound):
        await _report("ZZZZQ")
    assert "ZZZZQ" not in orp._locks
