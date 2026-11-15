"""The daily IV snapshot run (ADR 0008), with the database and Yahoo faked:
which tickers, when it writes nothing, and how one failure is contained."""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, date, datetime
from typing import Any

import pytest

from app.core import settings as settings_module
from app.services import market_calendar as mc
from app.services import options_snapshots as snaps

SATURDAY = datetime(2026, 11, 14, 17, tzinfo=UTC)  # after Friday 13 Nov's session
FRIDAY = date(2026, 11, 13)
FIRST_RUN = datetime(2026, 11, 13, 22, 17, tzinfo=UTC)  # the cron's first run, 1 h 17 min after the close
NIGHT_RUN = datetime(2026, 11, 14, 0, 47, tzinfo=UTC)  # its retry, 3 h 47 min after


class _Session:
    """Tracks whether a transaction (so a pooled connection) is open, and
    whether a failed statement left it needing a rollback."""

    def __init__(self) -> None:
        self.in_tx = False
        self.needs_rollback = False

    async def rollback(self) -> None:
        self.in_tx = False
        self.needs_rollback = False

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
        self.bad_rows: set[str] = set()
        # The full-chain open interest totals (PR 4).
        self.totals_stored: set[str] = set()
        self.totals_inserted: list[dict[str, Any]] = []
        self.totals_fetched: list[str] = []
        self.totals_outcomes: dict[str, Any] = {}
        self.calls: list[str] = []  # "snapshot:X" and "totals:X", in order

    async def stored_symbols(self, session: _Session, trade_date: date) -> set[str]:
        session.in_tx = True
        assert trade_date == FRIDAY
        return set(self.stored)

    async def tracked_symbols(self, session: _Session, since: datetime) -> list[str]:
        session.in_tx = True
        return list(self.tracked)

    async def insert_snapshot(self, session: _Session, row: dict[str, Any]) -> bool:
        # Like the real store: each write commits on its own, and a failed
        # statement leaves the session unusable until it rolls back.
        assert not session.needs_rollback, "PendingRollbackError"
        session.in_tx = True
        if row["symbol"] in self.bad_rows:
            session.needs_rollback = True
            raise ValueError("Postgres rejected the row")
        written = row["symbol"] not in self.stored
        if written:
            self.inserted.append(row)
            self.stored.add(row["symbol"])
        await session.commit()
        return written

    def snapshot_one(
        self, symbol: str, session_date: date, quoted_at: datetime, rate: float, rate_assumed: bool
    ) -> Any:
        assert session_date == FRIDAY
        assert not self.session.in_tx, "a database connection was held during the Yahoo fetch"
        assert quoted_at == mc.session_close(FRIDAY)
        self.fetched.append(symbol)
        self.calls.append(f"snapshot:{symbol}")
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

    async def stored_totals(self, session: _Session, trade_date: date) -> set[str]:
        session.in_tx = True
        assert trade_date == FRIDAY
        return set(self.totals_stored)

    async def insert_totals(self, session: _Session, row: dict[str, Any]) -> bool:
        session.in_tx = True
        written = row["symbol"] not in self.totals_stored
        if written:
            self.totals_inserted.append(row)
            self.totals_stored.add(row["symbol"])
        await session.commit()
        return written

    def chain_totals_one(self, symbol: str, session_date: date, quoted_at: datetime) -> Any:
        assert session_date == FRIDAY
        assert not self.session.in_tx, "a database connection was held during the full-chain fetch"
        self.totals_fetched.append(symbol)
        self.calls.append(f"totals:{symbol}")
        outcome = self.totals_outcomes.get(symbol, "ok")
        if isinstance(outcome, list):
            outcome = outcome.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        row = {"symbol": symbol, "trade_date": FRIDAY, "call_open_interest": 10, "put_open_interest": 9, "expiries": 24, "listed": 24}
        if outcome == "partial":
            return "partial", {**row, "expiries": 23}
        if outcome != "ok":
            return outcome, None
        return "ok", row


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
    monkeypatch.setattr(snaps.options_chain, "risk_free_rate", lambda: (0.04, False))
    monkeypatch.setattr(snaps, "_sleep", w.sleep)
    monkeypatch.setattr(settings_module.settings, "OPTIONS_FULL_CHAIN_SYMBOLS", "")
    monkeypatch.setattr(snaps.store, "stored_totals", w.stored_totals)
    monkeypatch.setattr(snaps.store, "insert_totals", w.insert_totals)
    monkeypatch.setattr(snaps, "chain_totals_one", w.chain_totals_one)
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

    monkeypatch.setattr(snaps.options_chain, "risk_free_rate", rate)
    await _run(world)
    assert calls == [1]


def test_rate_limit_errors_are_recognised_by_name() -> None:
    assert snaps.is_rate_limit(YFRateLimitError())
    assert not snaps.is_rate_limit(RuntimeError("Too Many Requests"))


async def test_the_run_never_blocks_the_event_loop(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    """The fetch runs on the options thread, so the loop keeps serving
    while it's in progress. (DeepSeek on PR 109: the first version of this
    test passed with the fetch called inline.)"""
    fetching = threading.Event()
    seen_mid_fetch: list[bool] = []
    real = world.snapshot_one

    def slow(*args: Any) -> Any:
        fetching.set()
        time.sleep(0.05)
        fetching.clear()
        return real(*args)

    monkeypatch.setattr(snaps, "snapshot_one", slow)
    done = asyncio.Event()

    async def heartbeat() -> None:
        while not done.is_set():
            seen_mid_fetch.append(fetching.is_set())
            await asyncio.sleep(0.005)

    async def run() -> None:
        await _run(world)
        done.set()

    await asyncio.gather(run(), heartbeat())
    assert any(seen_mid_fetch), "the event loop never ran while a fetch was in progress"


def test_a_ticker_is_keyed_on_the_session_not_its_last_print(monkeypatch: pytest.MonkeyPatch) -> None:
    """DeepSeek on PR 109: a thin name whose last underlying print was
    Thursday would be keyed on Thursday on a Friday run, collide, and
    leave Friday unwritten. The row takes the session's date; the print's
    own date goes into the detail."""
    from app.services import options_metrics as om
    from app.services.options_chain import ChainFetch

    thursday = datetime(2026, 11, 12, 21, tzinfo=UTC)
    fetched = ChainFetch(
        symbol="THIN", spot=10.0, market_time=int(thursday.timestamp()), dividend_yield=0.0,
        expiries=(), chains={}, closes=(),
    )
    canned = om.SnapshotMetrics(
        status="ok", iv30=0.4, iv30_extrapolated=False, iv90=None, iv90_extrapolated=False, skew25=None,
        rv20=None, rv60=None, call_open_interest=0, put_open_interest=0, call_volume=0, put_volume=0,
        detail={"method_version": 1, "expiries": []},
    )
    monkeypatch.setattr(snaps.options_chain, "fetch_chain", lambda *_a: fetched)
    monkeypatch.setattr(snaps.om, "snapshot_metrics", lambda *_a, **_k: canned)

    status, row = snaps.snapshot_one("THIN", FRIDAY, mc.session_close(FRIDAY), 0.04, False)

    assert status == "ok" and row is not None
    assert row["trade_date"] == FRIDAY
    assert row["detail"]["underlying_date"] == "2026-11-12"


async def test_a_failed_insert_does_not_lose_the_rest_of_the_day(world: _World) -> None:
    """DeepSeek on PR 109: a failed statement left the session needing a
    rollback, and every later ticker's insert failed with it."""
    world.bad_rows = {"SPY"}
    result = await _run(world)
    assert result.written == ["QQQ", "NVDA"]
    assert [(f.symbol, f.reason) for f in result.failed] == [("SPY", "ValueError")]


def test_a_fetch_with_no_spot_at_all_stores_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """DeepSeek on PR 109: no regularMarketPrice stored a $0 spot forever.
    fetch_chain now falls back to the last close itself
    (test_options_chain); with no close either, nothing is stored."""
    from app.services import options_metrics as om
    from app.services.options_chain import ChainFetch

    fetched = ChainFetch(
        symbol="NEW", spot=0.0, market_time=0, dividend_yield=0.0, expiries=(), chains={}, closes=(),
    )
    canned = om.SnapshotMetrics(
        status="ok", iv30=0.4, iv30_extrapolated=False, iv90=None, iv90_extrapolated=False, skew25=None,
        rv20=None, rv60=None, call_open_interest=0, put_open_interest=0, call_volume=0, put_volume=0,
        detail={"method_version": 1, "expiries": []},
    )
    monkeypatch.setattr(snaps.options_chain, "fetch_chain", lambda *_a: fetched)
    monkeypatch.setattr(snaps.om, "snapshot_metrics", lambda *_a, **_k: canned)

    status, row = snaps.snapshot_one("NEW", FRIDAY, mc.session_close(FRIDAY), 0.04, False)

    assert (status, row) == ("no_usable_quotes", None)


async def test_missing_names_the_configured_tickers_without_a_row(world: _World) -> None:
    """The cron fails on these: a configured ticker with no row for the
    session is a day lost (or a ticker that should not be configured)."""
    world.outcomes = {"SPY": "no_usable_quotes", "NVDA": KeyError("x")}
    world.tracked = ["THIN"]
    world.outcomes["THIN"] = "no_options"
    result = await _run(world)
    assert result.missing == ["SPY", "NVDA"]


async def test_the_nights_retry_is_not_failed_by_a_tracked_ticker_it_cannot_write(world: _World) -> None:
    """DeepSeek on PR 109: judged on what was left to write, the retry
    failed every night once a tracked name had no usable quotes."""
    world.stored = {"QQQ", "SPY", "NVDA"}
    world.tracked = ["THIN"]
    world.outcomes = {"THIN": "no_usable_quotes"}
    result = await _run(world)
    assert result.no_usable_quotes == ["THIN"]
    assert result.missing == []


async def test_nothing_missing_when_every_configured_ticker_is_stored(world: _World) -> None:
    result = await _run(world)
    assert result.missing == []


async def test_a_delisted_ticker_is_named_not_found(world: _World) -> None:
    """DeepSeek on PR 110: fetch_chain raises SymbolNotFound now."""
    from app.services.options_chain import SymbolNotFound

    world.outcomes = {"SPY": SymbolNotFound("SPY")}
    result = await _run(world)
    assert [(f.symbol, f.reason) for f in result.failed] == [("SPY", "not_found")]
    assert result.written == ["QQQ", "NVDA"]


# --- Full-chain open interest totals (PR 4) ---------------------------------


@pytest.fixture
def full_chain(world: _World, monkeypatch: pytest.MonkeyPatch) -> _World:
    monkeypatch.setattr(settings_module.settings, "OPTIONS_FULL_CHAIN_SYMBOLS", "SPY,NVDA")
    return world


async def test_totals_follow_every_snapshot_for_the_configured_tickers(full_chain: _World) -> None:
    run = await _run(full_chain)
    assert run.status == "ok"
    assert run.written == ["QQQ", "SPY", "NVDA"]
    assert run.totals_written == ["SPY", "NVDA"]
    assert [r["symbol"] for r in full_chain.totals_inserted] == ["SPY", "NVDA"]
    # The snapshots never wait on the slower full-chain reads.
    assert full_chain.calls == ["snapshot:QQQ", "snapshot:SPY", "snapshot:NVDA", "totals:SPY", "totals:NVDA"]


async def test_stored_totals_are_not_read_again(full_chain: _World) -> None:
    full_chain.totals_stored = {"SPY"}
    run = await _run(full_chain)
    assert run.totals_skipped == ["SPY"]
    assert full_chain.totals_fetched == ["NVDA"]


async def test_a_session_with_everything_stored_is_no_new_session(full_chain: _World) -> None:
    full_chain.stored = {"QQQ", "SPY", "NVDA"}
    full_chain.totals_stored = {"SPY", "NVDA"}
    run = await _run(full_chain)
    assert run.status == "no_new_session"
    assert full_chain.fetched == [] and full_chain.totals_fetched == []


async def test_the_retry_run_fills_totals_the_first_run_missed(full_chain: _World) -> None:
    full_chain.stored = {"QQQ", "SPY", "NVDA"}
    full_chain.totals_stored = {"SPY"}
    run = await _run(full_chain)
    assert run.status == "ok"
    assert full_chain.fetched == []
    assert run.totals_written == ["NVDA"]


async def test_a_totals_failure_is_named_and_the_snapshots_stand(full_chain: _World) -> None:
    full_chain.totals_outcomes["SPY"] = RuntimeError("Yahoo answered nonsense")
    run = await _run(full_chain)
    assert run.written == ["QQQ", "SPY", "NVDA"]
    assert run.totals_written == ["NVDA"]
    assert [(f.symbol, f.reason) for f in run.failed] == [("SPY", "totals: RuntimeError")]
    assert run.missing == []


async def test_totals_share_the_runs_throttle_pause(full_chain: _World) -> None:
    full_chain.totals_outcomes["SPY"] = [YFRateLimitError(), YFRateLimitError()]
    run = await _run(full_chain)
    assert full_chain.sleeps == [snaps.RATE_LIMIT_PAUSE_SECONDS]
    assert run.totals_deferred == ["SPY", "NVDA"]


async def test_totals_wait_for_the_retry_when_the_budget_is_spent(
    full_chain: _World, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Three snapshot checks fit; by the first totals check the budget is gone.
    ticks = iter([0.0, 1.0, 2.0, 3.0, snaps.TIME_BUDGET_SECONDS + 1, snaps.TIME_BUDGET_SECONDS + 2, snaps.TIME_BUDGET_SECONDS + 3])
    monkeypatch.setattr(snaps, "_clock", lambda: next(ticks))
    run = await _run(full_chain)
    assert run.written == ["QQQ", "SPY", "NVDA"]
    assert run.totals_deferred == ["SPY", "NVDA"]
    assert full_chain.totals_fetched == []


async def test_no_full_chain_tickers_means_no_totals(world: _World) -> None:
    run = await _run(world)
    assert run.totals_written == [] and world.totals_fetched == []


def test_chain_totals_sum_every_expiry_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.options_chain import ChainFetch, ExpiryQuotes, Quote

    listed = (date(2026, 11, 16), date(2026, 11, 20), date(2027, 1, 15))
    asked: list[list[date]] = []

    def quotes(oi: int, vol: int) -> tuple[Quote, ...]:
        return (Quote(100.0, 1.0, 1.1, vol, oi, True), Quote(105.0, 0.5, 0.6, vol, oi, False))

    def fetch(symbol: str, pick: Any, **kwargs: Any) -> ChainFetch:
        chosen = list(pick(listed, {}))
        asked.append(chosen)
        assert kwargs.get("read_calendar") is False
        chains = {d: ExpiryQuotes(d, quotes(10 * (i + 1), 1), quotes(5 * (i + 1), 2)) for i, d in enumerate(chosen)}
        return ChainFetch(symbol=symbol, spot=100.0, market_time=0, dividend_yield=0.0, expiries=listed, chains=chains, closes=())

    monkeypatch.setattr(snaps.options_chain, "fetch_chain", fetch)
    status, row = snaps.chain_totals_one("SPY", FRIDAY, mc.session_close(FRIDAY))
    assert asked == [list(listed)]
    assert status == "ok" and row is not None
    # Two contracts a side in each expiry read, adjusted ones counted too.
    assert (row["call_open_interest"], row["put_open_interest"]) == (2 * (10 + 20 + 30), 2 * (5 + 10 + 15))
    assert (row["call_volume"], row["put_volume"]) == (6, 12)
    assert (row["expiries"], row["listed"]) == (3, 3)
    assert row["trade_date"] == FRIDAY


def test_chain_totals_of_a_ticker_without_options(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(snaps.options_chain, "fetch_chain", lambda *_a, **_k: None)
    assert snaps.chain_totals_one("BRK-A", FRIDAY, mc.session_close(FRIDAY)) == ("no_options", None)


async def test_a_short_read_waits_for_the_night_run(full_chain: _World) -> None:
    """#123 review: a row is never updated, so the first run leaves a read
    with an expiry missing to the night's run rather than store it short."""
    full_chain.totals_outcomes["SPY"] = "partial"
    run = await _run(full_chain, FIRST_RUN)
    assert run.totals_written == ["NVDA"]
    assert run.totals_deferred == ["SPY"]
    assert [r["symbol"] for r in full_chain.totals_inserted] == ["NVDA"]


async def test_the_night_run_keeps_a_short_read_with_its_count(full_chain: _World) -> None:
    """#124 review: a ticker Yahoo always reads short would otherwise never
    get a row. The row says how many expiries were read, and the page says so."""
    full_chain.totals_outcomes["SPY"] = "partial"
    run = await _run(full_chain, NIGHT_RUN)
    assert run.totals_written == ["SPY", "NVDA"] and run.totals_deferred == []
    spy = next(r for r in full_chain.totals_inserted if r["symbol"] == "SPY")
    assert (spy["expiries"], spy["listed"]) == (23, 24)


async def test_a_chain_listed_but_not_read_waits_then_is_named(full_chain: _World) -> None:
    full_chain.totals_outcomes["SPY"] = "unread"
    first = await _run(full_chain, FIRST_RUN)
    assert first.totals_deferred == ["SPY"] and first.failed == []
    full_chain.totals_outcomes["SPY"] = "unread"
    night = await _run(full_chain, NIGHT_RUN)
    assert [(f.symbol, f.reason) for f in night.failed] == [("SPY", "totals: unread")]
    assert all(r["symbol"] != "SPY" for r in full_chain.totals_inserted)


async def test_a_short_read_stays_deferred_when_the_throttle_stops_the_rest(full_chain: _World) -> None:
    full_chain.totals_outcomes["SPY"] = "partial"
    full_chain.totals_outcomes["NVDA"] = [YFRateLimitError(), YFRateLimitError()]
    run = await _run(full_chain, FIRST_RUN)
    assert run.totals_deferred == ["SPY", "NVDA"]


async def test_a_full_chain_ticker_without_options_is_named(full_chain: _World) -> None:
    full_chain.totals_outcomes["NVDA"] = "no_options"
    run = await _run(full_chain)
    assert [(f.symbol, f.reason) for f in run.failed] == [("NVDA", "totals: no_options")]


def _fetched(expiries: dict[date, tuple[int, int]], listed: tuple[date, ...]) -> Any:
    """A chain read: each expiry's (call rows, put rows), one contract of open interest 10 a row."""
    from app.services.options_chain import ChainFetch, ExpiryQuotes, Quote

    def side(n: int) -> tuple[Quote, ...]:
        return tuple(Quote(100.0 + k, 1.0, 1.1, 1, 10, True) for k in range(n))

    chains = {d: ExpiryQuotes(d, side(c), side(p)) for d, (c, p) in expiries.items()}
    return ChainFetch(symbol="SPY", spot=100.0, market_time=0, dividend_yield=0.0, expiries=listed, chains=chains, closes=())


LISTED = (date(2026, 11, 16), date(2026, 11, 20))


@pytest.mark.parametrize(
    ("read", "why"),
    [
        ({LISTED[0]: (1, 1)}, "an expiry Yahoo dropped"),
        ({LISTED[0]: (1, 1), LISTED[1]: (0, 1)}, "an expiry with its calls empty"),
    ],
)
def test_a_chain_read_short_an_expiry_is_partial_and_counts_only_whole_ones(
    monkeypatch: pytest.MonkeyPatch, read: dict[date, tuple[int, int]], why: str
) -> None:
    monkeypatch.setattr(snaps.options_chain, "fetch_chain", lambda *_a, **_k: _fetched(read, LISTED))
    status, row = snaps.chain_totals_one("SPY", FRIDAY, mc.session_close(FRIDAY))
    assert status == "partial", why
    assert row is not None
    assert (row["expiries"], row["listed"], row["call_open_interest"], row["put_open_interest"]) == (1, 2, 10, 10)


def test_a_chain_listed_with_nothing_read_is_unread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Not "no options": Yahoo listed expiries, so it's a failed read the night run tries again."""
    monkeypatch.setattr(snaps.options_chain, "fetch_chain", lambda *_a, **_k: _fetched({}, LISTED))
    assert snaps.chain_totals_one("SPY", FRIDAY, mc.session_close(FRIDAY)) == ("unread", None)
