"""The daily IV snapshot run (ADR 0008), with the database and Yahoo faked:
which tickers, when it writes nothing, and how one failure is contained."""
from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.core import settings as settings_module
from app.services import market_calendar as mc
from app.services import options_snapshots as snaps

SATURDAY = datetime(2026, 11, 14, 17, tzinfo=UTC)  # after Friday 13 Nov's session
FRIDAY = date(2026, 11, 13)


class _Session:
    """Tracks whether a transaction (so a pooled connection) is open."""

    def __init__(self) -> None:
        self.in_tx = False

    async def rollback(self) -> None:
        self.in_tx = False

    async def commit(self) -> None:
        self.in_tx = False


class _World:
    """The faked store and Yahoo, recording what the run did."""

    def __init__(self, session: _Session) -> None:
        self.session = session
        self.stored: set[str] = set()
        self.tracked: list[str] = []
        self.inserted: list[dict[str, Any]] = []
        self.fetched: list[str] = []
        self.outcomes: dict[str, Any] = {}  # symbol -> status, or an exception (or a list of them)
        self.sleeps: list[float] = []

    async def stored_symbols(self, session: _Session, trade_date: date) -> set[str]:
        session.in_tx = True
        assert trade_date == FRIDAY
        return set(self.stored)

    async def tracked_symbols(self, session: _Session, since: datetime) -> list[str]:
        session.in_tx = True
        return list(self.tracked)

    async def insert_snapshot(self, session: _Session, row: dict[str, Any]) -> bool:
        # Like the real store: each write commits on its own.
        session.in_tx = True
        written = row["symbol"] not in self.stored
        if written:
            self.inserted.append(row)
            self.stored.add(row["symbol"])
        await session.commit()
        return written

    def snapshot_one(self, symbol: str, quoted_at: datetime, rate: float, rate_assumed: bool) -> Any:
        assert not self.session.in_tx, "a database connection was held during the Yahoo fetch"
        assert quoted_at == mc.session_close(FRIDAY)
        self.fetched.append(symbol)
        outcome = self.outcomes.get(symbol, "ok")
        if isinstance(outcome, list):
            outcome = outcome.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome != "ok":
            return outcome, None
        return "ok", {"symbol": symbol, "trade_date": FRIDAY, "iv30": 0.25}

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)


class YFRateLimitError(Exception):
    """Named like yfinance's, which is how the run recognises it."""


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> _World:
    session = _Session()
    w = _World(session)
    monkeypatch.setattr(settings_module.settings, "OPTIONS_SNAPSHOT_SYMBOLS", "QQQ,SPY,NVDA")
    monkeypatch.setattr(snaps.store, "stored_symbols", w.stored_symbols)
    monkeypatch.setattr(snaps.store, "tracked_symbols", w.tracked_symbols)
    monkeypatch.setattr(snaps.store, "insert_snapshot", w.insert_snapshot)
    monkeypatch.setattr(snaps, "snapshot_one", w.snapshot_one)
    monkeypatch.setattr(snaps, "risk_free_rate", lambda: (0.04, False))
    monkeypatch.setattr(snaps, "_sleep", w.sleep)
    return w


async def _run(world: _World, now: datetime = SATURDAY) -> Any:
    return await snaps.run_snapshots(world.session, now=now)  # type: ignore[arg-type]


def test_configured_symbols_are_cleaned() -> None:
    assert snaps.parse_symbols(" qqq, SPY,,nvda, bad sym, ../x, BRK-B, SPY ") == ["QQQ", "SPY", "NVDA", "BRK-B"]


async def test_targets_are_the_configured_then_the_tracked_capped(world: _World) -> None:
    world.tracked = ["AAPL", "SPY", "KO"]
    assert await snaps.targets(world.session, SATURDAY) == ["QQQ", "SPY", "NVDA", "AAPL", "KO"]  # type: ignore[arg-type]
    world.tracked = [f"T{i}" for i in range(40)]
    assert len(await snaps.targets(world.session, SATURDAY)) == snaps.MAX_TARGETS  # type: ignore[arg-type]


async def test_writes_one_row_per_ticker_for_the_last_session(world: _World) -> None:
    result = await _run(world)
    assert result.status == "ok"
    assert result.session_date == FRIDAY
    assert result.written == ["QQQ", "SPY", "NVDA"]
    assert [r["symbol"] for r in world.inserted] == ["QQQ", "SPY", "NVDA"]


async def test_refuses_while_the_market_is_open(world: _World) -> None:
    result = await _run(world, datetime(2026, 11, 16, 16, tzinfo=UTC))  # Monday 11:00 ET
    assert result.status == "market_open"
    assert world.fetched == []


async def test_a_session_already_stored_fetches_nothing(world: _World) -> None:
    """A weekend or holiday run, or the night's retry after a good run."""
    world.stored = {"QQQ", "SPY", "NVDA"}
    result = await _run(world)
    assert result.status == "no_new_session"
    assert result.skipped == ["QQQ", "SPY", "NVDA"]
    assert world.fetched == []


async def test_the_retry_run_fills_only_the_gaps(world: _World) -> None:
    world.stored = {"QQQ"}
    result = await _run(world)
    assert result.written == ["SPY", "NVDA"]
    assert result.skipped == ["QQQ"]
    assert world.fetched == ["SPY", "NVDA"]


async def test_tickers_without_options_or_quotes_are_named(world: _World) -> None:
    world.outcomes = {"SPY": "no_options", "NVDA": "no_usable_quotes"}
    result = await _run(world)
    assert result.written == ["QQQ"]
    assert result.no_options == ["SPY"]
    assert result.no_usable_quotes == ["NVDA"]


async def test_one_failure_does_not_stop_the_others(world: _World) -> None:
    world.outcomes = {"SPY": KeyError("regularMarketPrice")}
    result = await _run(world)
    assert result.written == ["QQQ", "NVDA"]
    assert [(f.symbol, f.reason) for f in result.failed] == [("SPY", "KeyError")]
    assert result.status == "ok"


async def test_a_rate_limit_pauses_once_then_defers_the_rest(world: _World) -> None:
    world.outcomes = {"SPY": [YFRateLimitError(), "ok"], "NVDA": YFRateLimitError()}
    world.tracked = ["AAPL"]
    result = await _run(world)
    assert world.sleeps == [snaps.RATE_LIMIT_PAUSE_SECONDS]
    assert result.written == ["QQQ", "SPY"]
    assert result.deferred == ["NVDA", "AAPL"]


async def test_the_run_stops_at_its_time_budget(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter([0.0, 1.0, snaps.TIME_BUDGET_SECONDS + 1, snaps.TIME_BUDGET_SECONDS + 2])
    monkeypatch.setattr(snaps, "_clock", lambda: next(ticks))
    result = await _run(world)
    assert result.written == ["QQQ"]
    assert result.deferred == ["SPY", "NVDA"]


async def test_a_second_run_at_the_same_time_is_refused(world: _World) -> None:
    async with snaps._run_lock:
        with pytest.raises(snaps.SnapshotRunning):
            await _run(world)


async def test_the_run_reads_the_rate_once(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def rate() -> tuple[float, bool]:
        calls.append(1)
        return 0.041, True

    monkeypatch.setattr(snaps, "risk_free_rate", rate)
    await _run(world)
    assert calls == [1]


def test_rate_limit_errors_are_recognised_by_name() -> None:
    assert snaps.is_rate_limit(YFRateLimitError())
    assert not snaps.is_rate_limit(RuntimeError("Too Many Requests"))


async def test_the_run_never_blocks_the_event_loop(world: _World) -> None:
    """The fetch runs on the options thread, so the loop keeps serving."""
    loop_ticks: list[int] = []

    async def heartbeat() -> None:
        for _ in range(3):
            loop_ticks.append(1)
            await asyncio.sleep(0)

    await asyncio.gather(_run(world), heartbeat())
    assert len(loop_ticks) == 3
