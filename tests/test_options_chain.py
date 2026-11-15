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
        self.history_periods: list[str] = []
        self.unknown = False
        self.half_empty: set[str] = set()

    @property
    def calendar(self) -> Any:
        if isinstance(self._calendar, Exception):
            raise self._calendar
        return self._calendar

    def option_chain(self, date: str | None = None) -> SimpleNamespace:
        self.chain_calls.append(date)
        if not self._expiries:
            return SimpleNamespace(calls=None, puts=None, underlying=None)
        if date in self.half_empty:
            return SimpleNamespace(calls=_frame([(100.0, 2.0, 2.1, 1, 1, "REGULAR")]), puts=None, underlying=None)
        calls = _frame([(100.0, 2.0, 2.1, None, 10, "REGULAR"), (105.0, 0.5, 0.6, 7, 20, "REGULAR")])
        puts = _frame([(95.0, 0.4, 0.5, 3, 5, "REGULAR"), (100.0, 1.9, 2.0, 1, 4, "ADJUSTED")])
        return SimpleNamespace(calls=calls, puts=puts, underlying=self._underlying)

    @property
    def options(self) -> tuple[str, ...]:
        return self._expiries

    def history(self, period: str, auto_adjust: bool = True) -> pd.DataFrame:
        self.history_periods.append(period)
        if self.unknown == "no columns":
            return pd.DataFrame()
        if self.unknown:
            return pd.DataFrame({"Close": []})
        index = pd.DatetimeIndex(
            [pd.Timestamp("2026-11-12", tz="America/New_York"), pd.Timestamp("2026-11-13", tz="America/New_York")]
        )
        return pd.DataFrame({"Close": [99.0, 100.0]}, index=index)


_UNDERLYING = {
    "regularMarketPrice": 100.25,
    "regularMarketTime": 1_794_603_600,
    "trailingAnnualDividendYield": 0.01,
    "quoteType": "EQUITY",
}


def _install(monkeypatch: pytest.MonkeyPatch, ticker: _FakeTicker) -> None:
    fake = MagicMock()
    fake.Ticker.return_value = ticker
    monkeypatch.setitem(sys.modules, "yfinance", fake)


def test_reads_the_front_chain_from_the_first_call_and_only_the_picked_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticker = _FakeTicker(["2026-11-16", "2026-11-20", "2026-12-18"], _UNDERLYING)
    _install(monkeypatch, ticker)

    fetched = oc.fetch_chain("AAPL", lambda listed, _quote: [listed[0], listed[2]])

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

    chain = oc.fetch_chain("AAPL", lambda listed, _quote: listed).chains[date(2026, 11, 16)]  # type: ignore[union-attr]

    first = chain.calls[0]
    assert (first.strike, first.bid, first.ask, first.volume, first.open_interest) == (100.0, 2.0, 2.1, 0, 10)
    assert first.mid == pytest.approx(2.05)
    assert first.regular is True
    assert chain.puts[1].regular is False  # an ADJUSTED contract (after a split or merger)


def test_a_ticker_without_listed_options_reads_as_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeTicker([], None))
    assert oc.fetch_chain("BRK-A", lambda listed, _quote: listed) is None


def test_a_symbol_yahoo_does_not_know_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    """No options and no prices: a 404 on the page, not "no options"."""
    ticker = _FakeTicker([], None)
    ticker.unknown = True
    _install(monkeypatch, ticker)
    with pytest.raises(oc.SymbolNotFound):
        oc.fetch_chain("ZZZZQ", lambda listed, _quote: listed)


def test_an_expiry_yahoo_does_not_list_is_not_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    ticker = _FakeTicker(["2026-11-16"], _UNDERLYING)
    _install(monkeypatch, ticker)

    fetched = oc.fetch_chain("AAPL", lambda _listed, _quote: [date(2027, 1, 15)])

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
        ({"Earnings Date": date(2027, 1, 28)}, date(2027, 1, 28)),  # one date, not a list
        ({"Earnings Date": "soon"}, None),  # a shape we don't know
        (RuntimeError("yahoo"), None),  # never fails the chain
    ],
)
def test_reads_the_next_earnings_date_from_the_calendar(
    monkeypatch: pytest.MonkeyPatch, calendar: Any, expected: date | None
) -> None:
    _install(monkeypatch, _FakeTicker(["2026-11-16"], _UNDERLYING, calendar))
    fetched = oc.fetch_chain("AAPL", lambda listed, _quote: listed)
    assert fetched is not None and fetched.next_earnings == expected


def test_a_fund_has_no_earnings_and_its_calendar_is_not_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """Yahoo answers a fund's calendar with a 404 that yfinance logs as an
    error (QQQ and SPY, every run)."""
    etf = {**_UNDERLYING, "quoteType": "ETF"}
    _install(monkeypatch, _FakeTicker(["2026-11-16"], etf, {"Earnings Date": [date(2027, 1, 28)]}))
    fetched = oc.fetch_chain("QQQ", lambda listed, _quote: listed)
    assert fetched is not None and fetched.next_earnings is None


def test_an_expiry_missing_one_side_is_dropped_not_the_ticker(monkeypatch: pytest.MonkeyPatch) -> None:
    """DeepSeek on PR 109: puts None raised AttributeError and lost the day."""
    ticker = _FakeTicker(["2026-11-16", "2026-12-18"], _UNDERLYING)
    ticker.half_empty = {"2026-12-18"}
    _install(monkeypatch, ticker)
    fetched = oc.fetch_chain("AAPL", lambda listed, _quote: listed)
    assert fetched is not None and sorted(fetched.chains) == [date(2026, 11, 16)]


@pytest.mark.parametrize(("raw", "expected"), [(0.0216, 0.0216), (2.16, 0.0216), (None, 0.0)])
def test_the_dividend_yield_is_a_fraction(monkeypatch: pytest.MonkeyPatch, raw: Any, expected: float) -> None:
    """Yahoo sends trailingAnnualDividendYield as a fraction (KO 0.0216)
    beside dividendYield in percent (2.14); a percent read as a fraction
    would make the fallback forward 100 times wrong."""
    _install(monkeypatch, _FakeTicker(["2026-11-16"], {**_UNDERLYING, "trailingAnnualDividendYield": raw}))
    fetched = oc.fetch_chain("KO", lambda listed, _quote: listed)
    assert fetched is not None and fetched.dividend_yield == pytest.approx(expected)


def test_the_picker_sees_the_quote_and_the_fetch_carries_name_and_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The report fetches a stock's earnings schedule (not a fund's) before
    choosing expiries, so the picker gets the quote."""
    quote = {**_UNDERLYING, "longName": "Apple Inc.", "isEarningsDateEstimate": True}
    ticker = _FakeTicker(["2026-11-16"], quote)
    _install(monkeypatch, ticker)
    seen: list[str] = []

    def pick(listed: tuple[date, ...], underlying: dict[str, Any]) -> list[date]:
        seen.append(underlying["quoteType"])
        return list(listed)

    fetched = oc.fetch_chain("AAPL", pick, history_period="2y")
    assert seen == ["EQUITY"]
    assert fetched is not None
    assert (fetched.name, fetched.earnings_estimated, fetched.quote_type) == ("Apple Inc.", True, "EQUITY")
    assert ticker.history_periods == ["2y"]


def test_the_calendar_can_be_left_unread(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeTicker(["2026-11-16"], _UNDERLYING, {"Earnings Date": [date(2027, 1, 28)]}))
    fetched = oc.fetch_chain("AAPL", lambda listed, _quote: listed, read_calendar=False)
    assert fetched is not None and fetched.next_earnings is None


def test_a_frame_without_columns_is_not_found_too(monkeypatch: pytest.MonkeyPatch) -> None:
    """DeepSeek on PR 110: ["Close"] on a column-less frame raised KeyError (a 503)."""
    ticker = _FakeTicker([], None)
    ticker.unknown = "no columns"  # type: ignore[assignment]
    _install(monkeypatch, ticker)
    with pytest.raises(oc.SymbolNotFound):
        oc.fetch_chain("ZZZZQ", lambda listed, _quote: listed)

