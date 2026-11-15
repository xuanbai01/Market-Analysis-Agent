"""Reading Yahoo's option chains into plain values (ADR 0008)."""
from __future__ import annotations

import sys
from collections.abc import Sequence
from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.services import options_chain as oc

_COLUMNS = [
    "contractSymbol", "lastTradeDate", "strike", "lastPrice", "bid", "ask", "change",
    "percentChange", "volume", "openInterest", "impliedVolatility", "inTheMoney",
    "contractSize", "currency",
]


def _frame(rows: list[tuple[float, float, float, float | None, int, str]]) -> pd.DataFrame:
    """(strike, bid, ask, volume, open interest, contract size) rows in
    Yahoo's column layout."""
    return pd.DataFrame(
        [
            ["X", pd.Timestamp("2026-11-13", tz="UTC"), k, (b + a) / 2, b, a, 0.0, 0.0,
             float("nan") if v is None else v, oi, 0.3, False, size, "USD"]
            for k, b, a, v, oi, size in rows
        ],
        columns=_COLUMNS,
    )


class _FakeTicker:
    """Just enough of yfinance.Ticker: option_chain(), options, history()."""

    def __init__(
        self, expiries: Sequence[str], underlying: dict[str, Any] | None, calendar: Any = None
    ) -> None:
        self._expiries = tuple(expiries)
        self._underlying = underlying
        self._calendar = calendar if calendar is not None else {}
        self.chain_calls: list[str | None] = []

    @property
    def calendar(self) -> Any:
        if isinstance(self._calendar, Exception):
            raise self._calendar
        return self._calendar

    def option_chain(self, date: str | None = None) -> SimpleNamespace:
        self.chain_calls.append(date)
        if not self._expiries:
            return SimpleNamespace(calls=None, puts=None, underlying=None)
        calls = _frame([(100.0, 2.0, 2.1, None, 10, "REGULAR"), (105.0, 0.5, 0.6, 7, 20, "REGULAR")])
        puts = _frame([(95.0, 0.4, 0.5, 3, 5, "REGULAR"), (100.0, 1.9, 2.0, 1, 4, "ADJUSTED")])
        return SimpleNamespace(calls=calls, puts=puts, underlying=self._underlying)

    @property
    def options(self) -> tuple[str, ...]:
        return self._expiries

    def history(self, period: str, auto_adjust: bool = True) -> pd.DataFrame:
        index = pd.DatetimeIndex(
            [pd.Timestamp("2026-11-12", tz="America/New_York"), pd.Timestamp("2026-11-13", tz="America/New_York")]
        )
        return pd.DataFrame({"Close": [99.0, 100.0]}, index=index)


_UNDERLYING = {"regularMarketPrice": 100.25, "regularMarketTime": 1_794_603_600, "trailingAnnualDividendYield": 0.01}


def _install(monkeypatch: pytest.MonkeyPatch, ticker: _FakeTicker) -> None:
    fake = MagicMock()
    fake.Ticker.return_value = ticker
    monkeypatch.setitem(sys.modules, "yfinance", fake)


def test_reads_the_front_chain_from_the_first_call_and_only_the_picked_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticker = _FakeTicker(["2026-11-16", "2026-11-20", "2026-12-18"], _UNDERLYING)
    _install(monkeypatch, ticker)

    fetched = oc.fetch_chain("AAPL", lambda listed: [listed[0], listed[2]])

    assert fetched is not None
    assert ticker.chain_calls == [None, "2026-12-18"]  # the front chain came with the first call
    assert fetched.expiries == (date(2026, 11, 16), date(2026, 11, 20), date(2026, 12, 18))
    assert sorted(fetched.chains) == [date(2026, 11, 16), date(2026, 12, 18)]
    assert fetched.spot == 100.25
    assert fetched.market_time == 1_794_603_600
    assert fetched.dividend_yield == 0.01
    assert fetched.closes == ((date(2026, 11, 12), 99.0), (date(2026, 11, 13), 100.0))


def test_quotes_carry_plain_numbers_and_flag_adjusted_contracts(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeTicker(["2026-11-16"], _UNDERLYING))

    chain = oc.fetch_chain("AAPL", lambda listed: listed).chains[date(2026, 11, 16)]  # type: ignore[union-attr]

    first = chain.calls[0]
    assert (first.strike, first.bid, first.ask, first.volume, first.open_interest) == (100.0, 2.0, 2.1, 0, 10)
    assert first.mid == pytest.approx(2.05)
    assert first.regular is True
    assert chain.puts[1].regular is False  # an ADJUSTED contract (after a split or merger)


def test_a_ticker_without_listed_options_reads_as_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeTicker([], None))
    assert oc.fetch_chain("BRK-A", lambda listed: listed) is None


def test_an_expiry_yahoo_does_not_list_is_not_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    ticker = _FakeTicker(["2026-11-16"], _UNDERLYING)
    _install(monkeypatch, ticker)

    fetched = oc.fetch_chain("AAPL", lambda _listed: [date(2027, 1, 15)])

    assert fetched is not None and fetched.chains == {}
    assert ticker.chain_calls == [None]


def test_the_rate_is_the_13_week_bill_yield_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_irx() -> float | None:
        calls.append(1)
        return 4.21

    oc.clear_rate_cache()
    monkeypatch.setattr(oc, "fetch_irx", fake_irx)
    assert oc.risk_free_rate() == (pytest.approx(0.0421), False)
    assert oc.risk_free_rate() == (pytest.approx(0.0421), False)
    assert len(calls) == 1
    oc.clear_rate_cache()


def test_the_rate_falls_back_to_an_assumed_value_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> float | None:
        raise RuntimeError("yahoo down")

    oc.clear_rate_cache()
    monkeypatch.setattr(oc, "fetch_irx", broken)
    assert oc.risk_free_rate() == (oc.ASSUMED_RATE, True)
    oc.clear_rate_cache()


@pytest.mark.parametrize(
    ("calendar", "expected"),
    [
        ({"Earnings Date": [date(2027, 1, 28), date(2027, 2, 1)]}, date(2027, 1, 28)),
        ({"Earnings Date": [date(2026, 10, 30)]}, None),  # already past
        ({}, None),  # an ETF
        (RuntimeError("yahoo"), None),  # never fails the chain
    ],
)
def test_reads_the_next_earnings_date_from_the_calendar(
    monkeypatch: pytest.MonkeyPatch, calendar: Any, expected: date | None
) -> None:
    _install(monkeypatch, _FakeTicker(["2026-11-16"], _UNDERLYING, calendar))
    fetched = oc.fetch_chain("AAPL", lambda listed: listed)
    assert fetched is not None and fetched.next_earnings == expected
