"""The owner's open positions, live from tastytrade (ADR 0009, amended).

Read when the owner opens the page, kept 15 seconds in memory, never
stored or put in a prompt. Accounts are numbered, never named: a test
feeds a distinctive account number through every path and fails if it
reaches the response or a log line.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.v1 import dependencies as deps
from app.core import settings as settings_module
from app.main import app
from app.services import owner_positions as op
from app.services import tastytrade_client as tt

ACCOUNT = "5WZ9QX7T"  # distinctive: must never leave the service
OTHER = "5WZ9QX8U"
OWNER_KEY = "o" * 40  # plainly fake: a value that looks like a key trips Gitleaks


def _position(symbol: str, kind: str, quantity: str, direction: str, **extra: Any) -> dict[str, Any]:
    underlying = extra.pop("underlying", symbol.split()[0] if kind == "Equity Option" else symbol)
    return {
        "account-number": extra.pop("account", ACCOUNT),
        "symbol": symbol,
        "instrument-type": kind,
        "underlying-symbol": underlying,
        "quantity": quantity,
        "quantity-direction": direction,
        "average-open-price": extra.pop("average", "2.5"),
        "multiplier": extra.pop("multiplier", 100 if kind == "Equity Option" else 1),
        **extra,
    }


def _quote(symbol: str, mark: float, **extra: Any) -> dict[str, Any]:
    return {"symbol": symbol, "bid": mark - 0.05, "ask": mark + 0.05, "mark": mark, "updated-at": "2026-11-16T20:59:58.000+00:00", **extra}


class _Tastytrade:
    """A fake account: what tastytrade would answer, and every call made."""

    def __init__(self) -> None:
        self.accounts = [ACCOUNT]
        self.positions: dict[str, list[dict[str, Any]]] = {ACCOUNT: []}
        self.quotes: dict[str, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.fail: Exception | None = None

    async def get(self, path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        self.calls.append((path, params))
        if self.fail is not None:
            raise self.fail
        if path == "/customers/me/accounts":
            return {"data": {"items": [{"account": {"account-number": n}} for n in self.accounts]}}
        if path.startswith("/accounts/") and path.endswith("/positions"):
            return {"data": {"items": self.positions.get(path.split("/")[2], [])}}
        if path == "/market-data/by-type":
            asked = [s for key in ("equity", "equity-option") for s in (params or {}).get(key, "").split(",") if s]
            return {"data": {"items": [self.quotes[s] for s in asked if s in self.quotes]}}
        raise AssertionError(f"unexpected path {path}")

    def quote_calls(self) -> list[dict[str, Any]]:
        return [p or {} for path, p in self.calls if path == "/market-data/by-type"]


@pytest.fixture
def account(monkeypatch: pytest.MonkeyPatch) -> _Tastytrade:
    fake = _Tastytrade()
    monkeypatch.setattr(op.tt, "get", fake.get)
    monkeypatch.setattr(op.tt, "is_configured", lambda: True)
    clock = [1000.0]
    monkeypatch.setattr(op, "_clock", lambda: clock[0])
    fake.clock = clock  # type: ignore[attr-defined]
    op.reset()
    yield fake
    op.reset()


# ── OCC symbols ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("symbol", "root", "expiry", "kind", "strike"),
    [
        ("SPY   261218C00600000", "SPY", date(2026, 12, 18), "call", 600.0),
        ("AAPL  261218P00187500", "AAPL", date(2026, 12, 18), "put", 187.5),
        ("BRKB  270115C00500000", "BRKB", date(2027, 1, 15), "call", 500.0),
        ("SPXW  261120P05900000", "SPXW", date(2026, 11, 20), "put", 5900.0),
        ("SPY1  261218C00600000", "SPY1", date(2026, 12, 18), "call", 600.0),
    ],
)
def test_an_occ_symbol_is_read_field_by_field(symbol: str, root: str, expiry: date, kind: str, strike: float) -> None:
    parsed = op.parse_occ(symbol)
    assert (parsed.root, parsed.expiry, parsed.kind, parsed.strike) == (root, expiry, kind, strike)


@pytest.mark.parametrize(
    "symbol", ["", "SPY261218C600", "SPY   261218X00600000", "SPY   261318C00600000", "SPY   261218C0060000", "spy   261218C00600000"]
)
def test_a_malformed_occ_symbol_is_refused_not_guessed(symbol: str) -> None:
    with pytest.raises(ValueError):
        op.parse_occ(symbol)


# ── Building the positions ──────────────────────────────────────────────


async def test_positions_are_grouped_by_underlying_with_signs_and_quotes(account: _Tastytrade) -> None:
    account.positions[ACCOUNT] = [
        _position("NVDA  261218C00200000", "Equity Option", "2", "Short", average="4.10"),
        _position("NVDA", "Equity", "200", "Long", average="150.25"),
        _position("SPY   261120P00650000", "Equity Option", "1", "Long", average="3.00"),
        _position("SPY   261218P00630000", "Equity Option", "1", "Short", average="1.20"),
        _position("/ESZ6", "Future", "1", "Long", underlying="/ES"),
    ]
    account.quotes = {
        "NVDA  261218C00200000": _quote("NVDA  261218C00200000", 3.2, volatility=0.48, delta=0.31, gamma=0.012, theta=-0.09, vega=0.21),
        "NVDA": _quote("NVDA", 162.9),
        "SPY   261120P00650000": _quote("SPY   261120P00650000", 2.1),
        "SPY": _quote("SPY", 671.0),
    }
    result = await op.get_positions()
    assert result.accounts == 1 and result.stale is False and result.source == "tastytrade"
    assert [g.underlying for g in result.groups] == ["NVDA", "SPY"]
    nvda, spy = result.groups
    call = next(leg for leg in nvda.legs if leg.kind == "call")
    stock = next(leg for leg in nvda.legs if leg.kind == "stock")
    assert (call.quantity, call.multiplier, call.strike, call.expiry, call.average_open) == (-2, 100, 200.0, date(2026, 12, 18), 4.10)
    assert (stock.quantity, stock.multiplier, stock.strike, stock.expiry) == (200, 1, None, None)
    assert call.quote is not None and (call.quote.mark, call.quote.iv, call.quote.delta, call.quote.theta) == (3.2, 0.48, 0.31, -0.09)
    assert nvda.quote is not None and nvda.quote.mark == 162.9
    assert nvda.expiries == [date(2026, 12, 18)]
    assert spy.expiries == [date(2026, 11, 20), date(2026, 12, 18)]
    assert next(leg for leg in spy.legs if leg.strike == 630).quote is None  # tastytrade sent none: no figure made up
    assert [(u.instrument_type, u.symbol, u.quantity) for u in result.unanalysed] == [("Future", "/ESZ6", 1)]


async def test_an_adjusted_contract_is_kept_and_flagged(account: _Tastytrade) -> None:
    account.positions[ACCOUNT] = [
        _position("SPY1  261218C00600000", "Equity Option", "1", "Long", underlying="SPY"),
        _position("SPY   261218C00600000", "Equity Option", "1", "Long", multiplier=10),
        _position("SPY   261218C00610000", "Equity Option", "1", "Long"),
    ]
    (group,) = (await op.get_positions()).groups
    assert [leg.adjusted for leg in group.legs] == [True, True, False]


async def test_a_ticker_with_a_slash_gets_its_dashed_form_for_our_pages(account: _Tastytrade) -> None:
    account.positions[ACCOUNT] = [_position("BRKB  270115C00500000", "Equity Option", "1", "Long", underlying="BRK/B")]
    (group,) = (await op.get_positions()).groups
    assert (group.underlying, group.symbol) == ("BRK/B", "BRK-B")


async def test_a_zero_or_unreadable_row_is_left_out(account: _Tastytrade) -> None:
    account.positions[ACCOUNT] = [
        _position("SPY   261218C00600000", "Equity Option", "0", "Zero"),
        _position("SPY   2612", "Equity Option", "1", "Long"),
        _position("SPY   261218C00610000", "Equity Option", "x", "Long"),
    ]
    result = await op.get_positions()
    assert result.groups == []
    assert [u.symbol for u in result.unanalysed] == ["SPY   2612", "SPY   261218C00610000"]


@pytest.mark.parametrize("multiplier", ["NaN", "Infinity", "-100", "0", "12.5", "lots"])
async def test_a_multiplier_that_is_not_a_whole_count_is_not_analysed(account: _Tastytrade, multiplier: str) -> None:
    """One bad row must not take the page down (positions PR 2's security review)."""
    account.positions[ACCOUNT] = [
        _position("SPY   261218C00600000", "Equity Option", "1", "Long", multiplier=multiplier),
        _position("SPY   261218C00610000", "Equity Option", "1", "Long"),
    ]
    result = await op.get_positions()
    assert [leg.strike for leg in result.groups[0].legs] == [610.0]
    assert [u.symbol for u in result.unanalysed] == ["SPY   261218C00600000"]


async def test_a_figure_that_is_not_finite_is_no_figure(account: _Tastytrade) -> None:
    """NaN or infinity would make the route a 500 (JSON can't carry them),
    and the copy would stay cached (positions PR 2's security review)."""
    account.positions[ACCOUNT] = [
        _position("SPY   261218C00600000", "Equity Option", "1", "Long", average="NaN"),
        _position("SPY   261218C00610000", "Equity Option", "Infinity", "Long"),
    ]
    account.quotes = {"SPY   261218C00600000": _quote("SPY   261218C00600000", 3.0, volatility="NaN", delta="-Infinity")}
    result = await op.get_positions()
    (leg,) = result.groups[0].legs
    assert leg.average_open is None and leg.quote is not None and (leg.quote.iv, leg.quote.delta) == (None, None)
    assert [u.symbol for u in result.unanalysed] == ["SPY   261218C00610000"]
    result.model_dump_json()  # serialisable


@pytest.mark.parametrize("direction", [None, "", "Sideways"])
async def test_a_position_that_does_not_say_long_or_short_is_not_guessed(account: _Tastytrade, direction: str | None) -> None:
    account.positions[ACCOUNT] = [_position("SPY   261218C00600000", "Equity Option", "1", direction)]  # type: ignore[arg-type]
    result = await op.get_positions()
    assert result.groups == []
    assert [(u.symbol, u.quantity) for u in result.unanalysed] == [("SPY   261218C00600000", None)]


@pytest.mark.parametrize("ticker", ["SPY,QQQ", "A" * 30, "spy", "../x", ""])
async def test_a_stock_or_underlying_that_is_not_a_ticker_is_not_analysed(account: _Tastytrade, ticker: str) -> None:
    account.positions[ACCOUNT] = [
        _position(ticker, "Equity", "10", "Long"),
        _position("SPY   261218C00600000", "Equity Option", "1", "Long", underlying=ticker),
    ]
    result = await op.get_positions()
    assert result.groups == []
    assert len(result.unanalysed) == 2
    assert all(ticker not in (p or {}).get("equity", "") for p in account.quote_calls())


async def test_a_huge_account_is_cut_off_and_says_so(account: _Tastytrade) -> None:
    account.positions[ACCOUNT] = [
        _position(f"SPY   2612{d:02d}C00{500 + s:03d}000", "Equity Option", "1", "Long")
        for d in range(1, 29) for s in range(30)
    ]
    result = await op.get_positions()
    assert result.truncated is True
    assert sum(len(g.legs) for g in result.groups) + len(result.unanalysed) == op.MAX_POSITIONS


async def test_an_account_tastytrade_cannot_find_is_skipped(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    account.accounts = [ACCOUNT, OTHER]
    account.positions = {OTHER: [_position("SPY   261218C00600000", "Equity Option", "1", "Long", account=OTHER)]}
    real = account.get

    async def gone(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        if path == f"/accounts/{ACCOUNT}/positions":
            raise tt.TastytradeNotFound("/accounts/***/positions")
        return await real(path, params, op=op)

    monkeypatch.setattr(op.tt, "get", gone)
    result = await op.get_positions()
    assert result.accounts == 1 and [leg.account for leg in result.groups[0].legs] == [2]  # one read; labels keep their place


async def test_a_build_that_runs_too_long_is_a_failure(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        await asyncio.sleep(1)
        return {}

    monkeypatch.setattr(op.tt, "get", slow)
    monkeypatch.setattr(op, "BUILD_SECONDS", 0.01)
    with pytest.raises(op.PositionsUnavailable, match="too long"):
        await op.get_positions()


async def test_no_account_is_not_remembered_for_an_hour(account: _Tastytrade) -> None:
    account.accounts = []
    assert (await op.get_positions()).accounts == 0
    account.accounts = [ACCOUNT]
    account.clock[0] += op.CACHE_SECONDS + 1  # type: ignore[attr-defined]
    assert (await op.get_positions()).accounts == 1


@pytest.mark.parametrize("payload", [[], "x", {"data": []}, {"data": {"items": {"a": 1}}}])
async def test_an_answer_of_the_wrong_shape_is_a_failure_not_an_empty_account(
    account: _Tastytrade, monkeypatch: pytest.MonkeyPatch, payload: object
) -> None:
    """A changed answer shape must not read as "no open positions" (#127's AI review)."""
    real = account.get

    async def odd(path: str, params: dict[str, Any] | None = None, *, op: str) -> object:
        return payload if path.endswith("/positions") else await real(path, params, op=op)

    monkeypatch.setattr(op.tt, "get", odd)
    with pytest.raises(op.PositionsUnavailable, match="readable"):
        await op.get_positions()


async def test_rows_that_are_not_records_are_skipped(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    real = account.get

    async def junk(path: str, params: dict[str, Any] | None = None, *, op: str) -> object:
        return {"data": {"items": ["x", 1]}} if path.endswith("/positions") else await real(path, params, op=op)

    monkeypatch.setattr(op.tt, "get", junk)
    result = await op.get_positions()
    assert (result.accounts, result.groups, result.unanalysed) == (1, [], [])


@pytest.mark.parametrize(("sent", "read"), [("0.48", 0.48), ("2.9", 2.9), ("48.0", None), ("0", None), ("-0.2", None)])
async def test_an_iv_that_cannot_be_a_fraction_is_no_figure(account: _Tastytrade, sent: str, read: float | None) -> None:
    """The page reads IV as a fraction; 48.0 would show as 4800% (#127's AI review)."""
    account.positions[ACCOUNT] = [_position("SPY   261218C00600000", "Equity Option", "1", "Long")]
    account.quotes = {"SPY   261218C00600000": _quote("SPY   261218C00600000", 3.0, volatility=sent)}
    (group,) = (await op.get_positions()).groups
    assert group.legs[0].quote is not None and group.legs[0].quote.iv == read


async def test_a_stock_is_one_share_per_unit_whatever_the_row_says(account: _Tastytrade) -> None:
    account.positions[ACCOUNT] = [_position("NVDA", "Equity", "200", "Long", multiplier=100)]
    (group,) = (await op.get_positions()).groups
    assert group.legs[0].multiplier == 1


async def test_a_quote_batch_that_fails_for_another_reason_is_not_retried_alone(
    account: _Tastytrade, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only a refusal is retried a symbol at a time: after a 5xx or a 429,
    25 more calls would only extend the trouble (#127's AI review)."""
    account.positions[ACCOUNT] = [_position("NVDA", "Equity", "10", "Long"), _position("AAPL", "Equity", "10", "Long")]
    real = account.get
    asked: list[dict[str, Any]] = []

    async def down(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        if path == "/market-data/by-type":
            asked.append(params or {})
            raise tt.TastytradeUnavailable("tastytrade failed 3 times (503)")
        return await real(path, params, op=op)

    monkeypatch.setattr(op.tt, "get", down)
    with pytest.raises(op.PositionsUnavailable):
        await op.get_positions()
    assert asked == [{"equity": "NVDA,AAPL"}]  # the batch once, nothing alone


@pytest.mark.parametrize("status", [401, 429])
async def test_a_401_or_429_is_not_a_refusal_to_retry_alone(
    account: _Tastytrade, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """A stale sign-in or a throttle isn't about the symbols (#127's AI review)."""
    account.positions[ACCOUNT] = [_position("NVDA", "Equity", "10", "Long"), _position("AAPL", "Equity", "10", "Long")]
    real = account.get
    asked: list[dict[str, Any]] = []

    async def no(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        if path == "/market-data/by-type":
            asked.append(params or {})
            raise tt.TastytradeUnavailable(f"tastytrade answered {status}", status=status)
        return await real(path, params, op=op)

    monkeypatch.setattr(op.tt, "get", no)
    with pytest.raises(op.PositionsUnavailable):
        await op.get_positions()
    assert len(asked) == 1


async def test_a_failure_reason_never_carries_an_account_number(account: _Tastytrade) -> None:
    account.fail = tt.TastytradeUnavailable(f"tastytrade answered 500 for /accounts/{ACCOUNT}/positions")
    with pytest.raises(op.PositionsUnavailable) as caught:
        await op.get_positions()
    assert ACCOUNT not in str(caught.value) and "/accounts/***/" in str(caught.value)


async def test_reading_stops_at_the_cap_and_asks_no_more_accounts(account: _Tastytrade) -> None:
    account.accounts = [ACCOUNT, OTHER]
    account.positions = {
        ACCOUNT: [_position(f"SPY   2612{d:02d}C00{500 + s:03d}000", "Equity Option", "1", "Long") for d in range(1, 29) for s in range(30)],
        OTHER: [_position("SPY   261218C00600000", "Equity Option", "1", "Long", account=OTHER)],
    }
    result = await op.get_positions()
    assert result.truncated is True
    assert not any(path == f"/accounts/{OTHER}/positions" for path, _ in account.calls)


async def test_an_account_entry_of_the_wrong_shape_is_skipped(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    real = account.get

    async def odd(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        if path == "/customers/me/accounts":
            return {"data": {"items": [{"account": "flat"}, {"account": {"account-number": ACCOUNT}}]}}
        return await real(path, params, op=op)

    monkeypatch.setattr(op.tt, "get", odd)
    assert (await op.get_positions()).accounts == 1


async def test_a_refused_quote_request_costs_only_its_own_quotes(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    """An index underlying (SPX) asked for as an equity may be refused; the
    option legs' quotes still come (#127's AI review)."""
    account.positions[ACCOUNT] = [_position("SPXW  261120P05900000", "Equity Option", "1", "Long", underlying="SPX")]
    account.quotes = {"SPXW  261120P05900000": _quote("SPXW  261120P05900000", 41.0)}
    real = account.get

    async def picky(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        if path == "/market-data/by-type" and "equity" in (params or {}):
            raise tt.TastytradeUnavailable("tastytrade answered 400", status=400)
        return await real(path, params, op=op)

    monkeypatch.setattr(op.tt, "get", picky)
    (group,) = (await op.get_positions()).groups
    assert group.quote is None and group.legs[0].quote is not None and group.legs[0].quote.mark == 41.0


async def test_one_refused_symbol_costs_only_its_own_quote(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    """A batch tastytrade refuses is asked for again a symbol at a time, so
    one index among stocks doesn't blank every underlying (#127's AI review)."""
    account.positions[ACCOUNT] = [
        _position("SPXW  261120P05900000", "Equity Option", "1", "Long", underlying="SPX"),
        _position("NVDA", "Equity", "10", "Long"),
    ]
    account.quotes = {"NVDA": _quote("NVDA", 162.9), "SPXW  261120P05900000": _quote("SPXW  261120P05900000", 41.0)}
    real = account.get

    async def no_spx(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        if path == "/market-data/by-type" and "SPX" in (params or {}).get("equity", "").split(","):
            raise tt.TastytradeUnavailable("tastytrade answered 400", status=400)
        return await real(path, params, op=op)

    monkeypatch.setattr(op.tt, "get", no_spx)
    groups = {g.underlying: g for g in (await op.get_positions()).groups}
    assert groups["NVDA"].quote is not None and groups["NVDA"].quote.mark == 162.9
    assert groups["SPX"].quote is None and groups["SPX"].legs[0].quote is not None


async def test_a_stock_row_without_a_multiplier_is_still_a_stock(account: _Tastytrade) -> None:
    row = _position("NVDA", "Equity", "200", "Long")
    del row["multiplier"]
    account.positions[ACCOUNT] = [row]
    (group,) = (await op.get_positions()).groups
    assert (group.legs[0].kind, group.legs[0].multiplier, group.legs[0].quantity) == ("stock", 1, 200)


async def test_more_accounts_than_one_read_takes_says_so(account: _Tastytrade) -> None:
    account.accounts = [f"5WZ9QX{i:02d}" for i in range(op.MAX_ACCOUNTS + 2)]
    result = await op.get_positions()
    assert result.accounts == op.MAX_ACCOUNTS and result.truncated is True


async def test_quotes_are_asked_for_at_most_a_hundred_at_a_time(account: _Tastytrade) -> None:
    account.positions[ACCOUNT] = [
        _position(f"SPY   261218C00{500 + i:03d}000", "Equity Option", "1", "Long") for i in range(150)
    ]
    await op.get_positions()
    calls = account.quote_calls()
    # The underlying on its own, then the 150 options in two.
    assert [sorted(p) for p in calls] == [["equity"], ["equity-option"], ["equity-option"]]
    for params in calls:
        assert sum(len(v.split(",")) for v in params.values()) <= op.QUOTE_BATCH


async def test_two_accounts_are_numbered_and_their_numbers_never_leave(
    account: _Tastytrade, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    account.accounts = [ACCOUNT, OTHER]
    account.positions = {
        ACCOUNT: [_position("SPY   261218C00600000", "Equity Option", "1", "Long")],
        OTHER: [_position("SPY   261218C00610000", "Equity Option", "1", "Short", account=OTHER)],
    }
    result = await op.get_positions()
    assert result.accounts == 2
    assert sorted(leg.account for leg in result.groups[0].legs) == [1, 2]
    text = result.model_dump_json()
    for number in (ACCOUNT, OTHER):
        assert number not in text
        assert number not in caplog.text


async def test_an_account_number_that_is_not_one_is_never_put_in_a_path(account: _Tastytrade) -> None:
    account.accounts = ["../orders", ACCOUNT]
    await op.get_positions()
    assert all("orders" not in path for path, _ in account.calls)


# ── Cache and failure ───────────────────────────────────────────────────


async def test_a_second_look_within_15_seconds_asks_tastytrade_nothing(account: _Tastytrade) -> None:
    await op.get_positions()
    asked = len(account.calls)
    account.clock[0] += op.CACHE_SECONDS - 1  # type: ignore[attr-defined]
    await op.get_positions()
    assert len(account.calls) == asked
    account.clock[0] += 2  # type: ignore[attr-defined]
    await op.get_positions()
    assert len(account.calls) > asked


async def test_a_failure_serves_the_last_copy_marked_stale(account: _Tastytrade) -> None:
    account.positions[ACCOUNT] = [_position("SPY   261218C00600000", "Equity Option", "1", "Long")]
    first = await op.get_positions()
    account.clock[0] += op.CACHE_SECONDS + 1  # type: ignore[attr-defined]
    account.fail = tt.TastytradeUnavailable("tastytrade didn't answer")
    again = await op.get_positions()
    assert again.stale is True and again.as_of == first.as_of and again.groups == first.groups


async def test_a_stale_copy_is_dropped_after_a_while(account: _Tastytrade) -> None:
    """tastytrade's figures are cached briefly (ADR 0009): not served for
    hours after the grant is revoked."""
    account.positions[ACCOUNT] = [_position("SPY   261218C00600000", "Equity Option", "1", "Long")]
    await op.get_positions()
    account.fail = tt.TastytradeUnavailable("the sign-in was refused")
    account.clock[0] += op.STALE_MAX_SECONDS - 1  # type: ignore[attr-defined]
    assert (await op.get_positions()).stale is True
    account.clock[0] += 2  # type: ignore[attr-defined]
    with pytest.raises(op.PositionsUnavailable, match="sign-in was refused"):
        await op.get_positions()
    account.fail = None
    account.clock[0] += 1  # type: ignore[attr-defined]
    assert (await op.get_positions()).stale is False  # and nothing old comes back


async def test_a_failure_with_nothing_cached_says_why(account: _Tastytrade) -> None:
    account.fail = tt.TastytradeUnavailable("the sign-in was refused")
    with pytest.raises(op.PositionsUnavailable, match="sign-in was refused"):
        await op.get_positions()


async def test_without_tastytrade_set_up_it_says_so(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(op.tt, "is_configured", lambda: False)
    with pytest.raises(op.PositionsUnavailable, match="isn't set up"):
        await op.get_positions()
    assert account.calls == []


# ── The route ───────────────────────────────────────────────────────────


@pytest.fixture
def owner(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", "")
    monkeypatch.setattr(settings_module.settings, "OWNER_KEY", SecretStr(OWNER_KEY))
    deps.reset_owner_failures_for_tests()
    return {deps.OWNER_HEADER: OWNER_KEY}


async def _get(headers: dict[str, str]) -> Any:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/v1/owner/positions", headers=headers)


async def test_the_route_needs_the_owner_key(account: _Tastytrade, owner: dict[str, str]) -> None:
    assert (await _get({})).status_code == 403
    assert account.calls == []


async def test_no_owner_response_is_kept_by_a_browser_errors_included(
    account: _Tastytrade, owner: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings_module.settings, "OWNER_KEY_FAILURES_PER_HOUR", 1)
    assert (await _get({deps.OWNER_HEADER: "wrong"})).headers["Cache-Control"] == "no-store"  # 403
    locked = await _get(owner)
    assert locked.status_code == 429 and locked.headers["Cache-Control"] == "no-store"
    deps.reset_owner_failures_for_tests()
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        status = await client.get("/v1/owner/status", headers=owner)
    assert status.status_code == 200 and status.headers["Cache-Control"] == "no-store"


async def test_the_route_serves_them_never_cached_by_a_browser(account: _Tastytrade, owner: dict[str, str]) -> None:
    account.positions[ACCOUNT] = [_position("SPY   261218C00600000", "Equity Option", "1", "Long")]
    resp = await _get(owner)
    assert resp.status_code == 200
    assert resp.headers["Cache-Control"] == "no-store"
    assert resp.json()["groups"][0]["underlying"] == "SPY"


async def test_even_an_unexpected_error_is_never_kept_by_a_browser(
    account: _Tastytrade, owner: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 500 is built outside the middleware that marks owner responses (#127's AI review)."""
    async def broken() -> None:
        raise RuntimeError("a bug")

    monkeypatch.setattr("app.api.v1.routers.owner.get_positions", broken)
    resp = await _get(owner)
    assert resp.status_code == 500 and resp.headers["Cache-Control"] == "no-store"


async def test_the_route_is_a_503_with_the_reason_when_tastytrade_fails(account: _Tastytrade, owner: dict[str, str]) -> None:
    account.fail = tt.TastytradeUnavailable("tastytrade didn't answer")
    resp = await _get(owner)
    assert resp.status_code == 503
    assert "didn't answer" in resp.json()["title"]  # problem+json puts a string detail in the title
    assert resp.headers["Cache-Control"] == "no-store"


async def test_a_quote_endpoint_that_is_gone_fails_the_read(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    """A 404 on the quotes call is about the endpoint, not a symbol: the read
    fails (stale copy, or a 503) rather than showing positions with no quotes
    anywhere (#127's AI review)."""
    account.positions[ACCOUNT] = [_position("NVDA", "Equity", "10", "Long")]
    real = account.get

    async def gone(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        if path == "/market-data/by-type":
            raise tt.TastytradeNotFound("/market-data/by-type")
        return await real(path, params, op=op)

    monkeypatch.setattr(op.tt, "get", gone)
    with pytest.raises(op.PositionsUnavailable):
        await op.get_positions()


async def test_every_symbol_refused_fails_the_read(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    account.positions[ACCOUNT] = [_position("NVDA", "Equity", "10", "Long"), _position("AAPL", "Equity", "10", "Long")]
    real = account.get

    async def refuses(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        if path == "/market-data/by-type":
            raise tt.TastytradeUnavailable("tastytrade answered 400", status=400)
        return await real(path, params, op=op)

    monkeypatch.setattr(op.tt, "get", refuses)
    with pytest.raises(op.PositionsUnavailable, match="refused every quote"):
        await op.get_positions()


async def test_a_quote_time_without_a_zone_is_utc(account: _Tastytrade) -> None:
    """Sent without an offset, the browser would read it as local time."""
    account.positions[ACCOUNT] = [_position("NVDA", "Equity", "10", "Long")]
    account.quotes = {"NVDA": {**_quote("NVDA", 162.9), "updated-at": "2026-11-16T20:59:58"}}
    (group,) = (await op.get_positions()).groups
    assert group.quote is not None and group.quote.updated_at is not None
    assert group.quote.updated_at.utcoffset() is not None and group.quote.updated_at.utcoffset().total_seconds() == 0

