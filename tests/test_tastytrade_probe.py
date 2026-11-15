"""The tastytrade probe (ADR 0009, PR A) prints metadata, never a
tastytrade value or anything that identifies the owner's account."""
from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.services import dxlink
from app.services import tastytrade_client as tt
from app.services import tastytrade_probe as probe

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime.now(UTC)
TODAY = NOW.astimezone(probe.mc.ET).date()
EXPIRY = (TODAY + timedelta(days=29)).isoformat()

# Distinctive values: none of them may reach the output.
SECRET_VALUES = (
    "603.21", "1.2345", "1.4345", "1.3345", "31.4159", "0.27182", "0.9876", "1.2468",
    "5WT12345", "1234.56", "512.34", "98765", "0.4242",
)


def _stamp(seconds_ago: float) -> str:
    """A quote time ``seconds_ago`` before the probe's (fixed) now."""
    return (NOW - timedelta(seconds=seconds_ago)).isoformat().replace("+00:00", "Z")


def _strike(k: int) -> dict[str, Any]:
    tag = f"{date.fromisoformat(EXPIRY):%y%m%d}"
    return {
        "strike-price": f"{k}.0",
        "call": f"SPY   {tag}C00{k}000",
        "call-streamer-symbol": f".SPY{tag}C{k}",
        "put": f"SPY   {tag}P00{k}000",
        "put-streamer-symbol": f".SPY{tag}P{k}",
    }


STRIKES = [_strike(k) for k in range(590, 616)]


async def fake_get(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
    params = params or {}
    if path == "/market-data/by-type":
        items = [{"symbol": "SPY", "instrument-type": "Equity", "mark": "603.21", "updated-at": _stamp(0.8)}]
        for symbol in filter(None, params.get("equity-option", "").split(",")):
            items.append({
                "symbol": symbol, "instrument-type": "Equity Option",
                "bid": "1.2345", "ask": "1.4345", "mid": "1.3345", "updated-at": _stamp(2.5),
            })
        return {"data": {"items": items}}
    if path == "/option-chains/SPY/nested":
        far = (TODAY + timedelta(days=90)).isoformat()
        return {"data": {"items": [{
            "underlying-symbol": "SPY", "root-symbol": "SPY",
            "expirations": [
                {"expiration-date": EXPIRY, "expiration-type": "Regular", "strikes": STRIKES},
                {"expiration-date": far, "expiration-type": "Regular", "strikes": STRIKES},
            ],
        }]}}
    if path == "/market-metrics":
        return {"data": {"items": [
            {"symbol": s, "implied-volatility-30-day": "31.4159", "implied-volatility-index-rank": "0.27182",
             "earnings": {"expected-report-date": "2026-11-19", "time-of-day": "AMC", "estimated": False}}
            for s in params["symbols"].split(",")
        ]}}
    if path.startswith("/market-metrics/historic-corporate-events/earnings-reports/"):
        return {"data": {"items": [{"occurred-date": "2015-05-07", "eps": "0.9876"}, {"occurred-date": "2026-08-27", "eps": "1.2468"}]}}
    if path == "/customers/me/accounts":
        return {"data": {"items": [{"account": {"account-number": "5WT12345", "nickname": "Individual"}}]}}
    if path == "/accounts/5WT12345/transactions":
        return {
            "data": {"items": [{"executed-at": "2021-03-04T15:00:00Z", "value": "-1234.56"}]},
            "pagination": {"total-items": 321},
        }
    if path == "/accounts/5WT12345/positions":
        return {"data": {"items": [{"symbol": "SPY", "quantity": "3", "average-open-price": "512.34"}]}}
    raise AssertionError(f"unexpected path {path}")


def _history(first: datetime, n: int, iv: float | None) -> dxlink.CandleHistory:
    candles = tuple(
        dxlink.Candle(first + timedelta(days=i), 603.21, 603.21, 603.21, 603.21, 98765.0, iv, None) for i in range(n)
    )
    return dxlink.CandleHistory(candles=candles, complete=True)


@pytest.fixture
def run(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    asked: list[tuple[str, str, bool]] = []

    async def fake_candles(symbol: str, period: str, from_time: datetime, *, time_unit_ms: bool = False) -> dxlink.CandleHistory:
        asked.append((symbol, period, time_unit_ms))
        return _history(from_time, 3, 0.4242 if period == "1d" else None)

    async def fake_once(event_type: str, symbols: list[str]) -> dict[str, dict[str, Any]]:
        return {s: {"eventType": event_type, "eventSymbol": s, "openInterest": 98765.0, "volatility": None} for s in symbols}

    async def fake_token() -> dxlink.QuoteToken:
        return dxlink.QuoteToken("qt-secret", "wss://tasty-openapi-ws.dxfeed.test/realtime", "api")

    async def fake_iv30(symbol: str) -> float:
        return 0.30

    async def fake_grant() -> frozenset[str]:
        return frozenset({"read", "accounts:5wt12345:owner"})

    monkeypatch.setattr(tt, "get", fake_get)
    monkeypatch.setattr(dxlink, "fetch_candles", fake_candles)
    monkeypatch.setattr(dxlink, "fetch_once", fake_once)
    monkeypatch.setattr(dxlink, "quote_token", fake_token)
    monkeypatch.setattr(probe, "_yahoo_quotes", lambda symbol, expiry: {
        (side, float(k)): (1.20, 1.50) for k in range(590, 616) for side in ("call", "put")
    })
    monkeypatch.setattr(probe, "_our_iv30", fake_iv30)
    monkeypatch.setattr(tt, "grant_scopes", fake_grant)
    monkeypatch.setattr(probe, "_now", lambda: NOW)
    lines: list[str] = []
    return lines


async def test_the_report_answers_the_open_questions(run: list[str]) -> None:
    await probe.main(run.append)
    report = "\n".join(run)
    assert "the stored grant may: ['accounts:***:owner', 'read']" in report
    assert "WARNING" not in report
    assert "level: api" in report
    assert "feed: tasty-openapi-ws.dxfeed.test/realtime" in report
    assert "delayed URL: no" in report
    assert "2 expirations; the one nearest 30 days has 26 strikes" in report
    assert "11 of 11 quotes came back" in report
    assert "SPY quote age: 0.8 s" in report
    assert "median 2.5 s" in report
    assert "inside Yahoo's (15-minute-old) bid–ask: 10 of 10" in report
    assert "IV30 within 2 points of our latest snapshot: yes" in report
    assert "fromTime in milliseconds" in report
    assert "with IV 3/3" in report
    assert "fields filled: ['openInterest']" in report
    assert "NVDA: 2 reports since 2015, 2015 to 2026" in report
    assert "1 account(s)" in report
    assert "321 transactions, the first in 2021-03; 1 open positions" in report
    assert "failed" not in report


async def test_the_report_holds_no_tastytrade_value_or_account_detail(run: list[str]) -> None:
    await probe.main(run.append)
    report = "\n".join(run)
    for value in (*SECRET_VALUES, "qt-secret"):
        assert value.lower() not in report.lower()


async def test_a_failing_section_is_reported_and_the_rest_runs(monkeypatch: pytest.MonkeyPatch, run: list[str]) -> None:
    async def refused(*args: Any, **kwargs: Any) -> Any:
        raise dxlink.DxlinkError("DXLink refused the quote token")

    monkeypatch.setattr(dxlink, "fetch_candles", refused)
    await probe.main(run.append)
    report = "\n".join(run)
    assert "failed: DxlinkError: DXLink refused the quote token" in report
    assert "1 account(s)" in report


def test_field_reads_dashed_and_camel_names() -> None:
    assert probe.field({"updated-at": "a"}, "updated-at") == "a"
    assert probe.field({"updatedAt": "b"}, "updated-at") == "b"
    assert probe.field({"streamerSymbol": "c"}, "streamer-symbol") == "c"
    assert probe.field({}, "updated-at") is None


def test_nearest_expiry_and_near_money() -> None:
    today = date(2026, 11, 16)
    expirations = [{"expiration-date": d} for d in ("2026-11-20", "2026-12-18", "2027-01-15")]
    assert probe.nearest_expiry(expirations, today)["expiration-date"] == "2026-12-18"
    assert probe.nearest_expiry([], today) is None
    strikes = [{"strike-price": str(k)} for k in (590, 595, 600, 605, 610)]
    assert [s["strike-price"] for s in probe.near_money(strikes, 601.0, 3)] == ["600", "605", "595"]


def test_the_checks_answer_yes_no_or_cant_tell() -> None:
    assert probe.spread_check(1.3, 1.2, 1.5) is True
    assert probe.spread_check(1.6, 1.2, 1.5) is False
    assert probe.spread_check(1.3, None, 1.5) is None
    assert probe.iv30_agrees(0.30, 31.9) is True
    assert probe.iv30_agrees(0.30, 32.5) is False
    assert probe.iv30_agrees(None, 31.0) is None
    assert probe.age_seconds("2026-11-16T15:00:00Z", datetime(2026, 11, 16, 15, 0, 3, tzinfo=UTC)) == 3.0
    assert probe.age_seconds("not a time", NOW) is None


def test_the_app_never_imports_the_probe() -> None:
    importing = re.compile(r"^\s*(from\s+\S*tastytrade_probe\b|import\s+.*\btastytrade_probe\b|from\s+app\.services\s+import\s+.*\btastytrade_probe\b)", re.M)
    for path in (ROOT / "app").rglob("*.py"):
        assert not importing.search(path.read_text(encoding="utf-8")), path


async def test_a_grant_that_can_trade_is_called_out(monkeypatch: pytest.MonkeyPatch, run: list[str]) -> None:
    async def trading_grant() -> frozenset[str]:
        return frozenset({"read", "trade"})

    monkeypatch.setattr(tt, "grant_scopes", trading_grant)
    await probe.main(run.append)
    report = "\n".join(run)
    assert "the stored grant may: ['read', 'trade']" in report
    assert "WARNING: the grant can trade" in report


async def test_an_account_number_in_an_odd_form_is_not_printed(monkeypatch: pytest.MonkeyPatch, run: list[str]) -> None:
    async def odd_accounts(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        if path == "/customers/me/accounts":
            return {"data": {"items": [{"account": {"account-number": "ab-98765"}}]}}
        return await fake_get(path, params, op=op)

    monkeypatch.setattr(tt, "get", odd_accounts)
    await probe.main(run.append)
    report = "\n".join(run)
    assert "no account number in the expected form" in report
    assert "98765" not in report


async def test_a_foreign_errors_text_is_never_printed(monkeypatch: pytest.MonkeyPatch, run: list[str]) -> None:
    async def db_down(symbol: str) -> float:
        raise OSError("could not connect to postgresql://postgres:hunter2@db.internal:5432/marketdb")

    async def leaky(*args: Any, **kwargs: Any) -> Any:
        raise ConnectionError("server closed with reason: mark 1.2345")

    monkeypatch.setattr(probe, "_our_iv30", db_down)
    monkeypatch.setattr(dxlink, "fetch_candles", leaky)
    await probe.main(run.append)
    report = "\n".join(run)
    assert "failed: ConnectionError" in report
    assert "our snapshot unreadable (OSError)" in report
    for value in ("hunter2", "db.internal", "1.2345"):
        assert value not in report


async def test_the_feed_address_prints_without_query_or_credentials(monkeypatch: pytest.MonkeyPatch, run: list[str]) -> None:
    async def token_in_url() -> dxlink.QuoteToken:
        return dxlink.QuoteToken("qt-secret", "wss://u:pw@tasty-openapi-ws.dxfeed.com/realtime?token=qt-secret", "api")

    monkeypatch.setattr(dxlink, "quote_token", token_in_url)
    await probe.main(run.append)
    report = "\n".join(run)
    assert "feed: tasty-openapi-ws.dxfeed.com/realtime;" in report
    assert "qt-secret" not in report and "pw" not in report.split("feed:")[1].split(";")[0]


async def test_strikes_that_arent_objects_are_not_printed(monkeypatch: pytest.MonkeyPatch, run: list[str]) -> None:
    async def array_strikes(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        if path == "/option-chains/SPY/nested":
            return {"data": {"items": [{"expirations": [{"expiration-date": EXPIRY, "strikes": [["603.21", "SPY C"]]}]}]}}
        return await fake_get(path, params, op=op)

    monkeypatch.setattr(tt, "get", array_strikes)
    await probe.main(run.append)
    report = "\n".join(run)
    assert "failed: ProbeError: the strikes are not objects" in report
    assert "603.21" not in report


def test_field_names_name_a_non_object_only_by_type() -> None:
    assert probe.field_names({"b": 1, "a": 2}) == ["a", "b"]
    assert probe.field_names(["603.21"]) == "<list>"
    assert probe.field_names("1.2345") == "<str>"


def test_a_nan_quote_from_yahoo_is_missing_not_outside() -> None:
    nan = float("nan")
    assert probe.spread_check(1.3, nan, nan) is None
    assert probe.spread_check(nan, 1.2, 1.5) is None
    assert probe.spread_check(1.3, 1.2, float("inf")) is None


def test_a_snipped_history_says_so() -> None:
    candle = dxlink.Candle(datetime(2020, 1, 2, tzinfo=UTC), 1.0, 1.0, 1.0, 1.0, 1.0, None, None)
    text = probe.describe_candles(dxlink.CandleHistory(candles=(candle,), complete=False, snipped=True))
    assert "complete=False, cut short by the server" in text
    assert "cut short" not in probe.describe_candles(dxlink.CandleHistory(candles=(candle,), complete=True))


async def test_strikes_without_streamer_symbols_are_reported_not_guessed(
    monkeypatch: pytest.MonkeyPatch, run: list[str]
) -> None:
    async def no_streamers(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        if path == "/option-chains/SPY/nested":
            strikes = [{k: v for k, v in s.items() if not k.endswith("streamer-symbol")} for s in STRIKES]
            return {"data": {"items": [{"expirations": [{"expiration-date": EXPIRY, "strikes": strikes}]}]}}
        return await fake_get(path, params, op=op)

    monkeypatch.setattr(tt, "get", no_streamers)
    await probe.main(run.append)
    report = "\n".join(run)
    assert "no near-money call with a streamer symbol: option candles not asked" in report
    assert "failed: ProbeError: no near-money call with a streamer symbol" in report


def test_an_expiry_whose_date_doesnt_read_is_skipped() -> None:
    today = date(2026, 11, 16)
    expirations = [
        {"expiration-date": ""},
        {"expiration-date": "2026-12-18T16:00:00Z"},
        {"expiration-date": None},
        "2026-12-17",
        {"expiration-date": "2027-01-15"},
        {"expiration-date": "2026-12-18"},
    ]
    assert probe._date(probe.nearest_expiry(expirations, today)["expiration-date"]) == date(2026, 12, 18)
    assert probe.nearest_expiry([{"expiration-date": "soon"}], today) is None


def test_an_expiry_given_as_a_timestamp_reads_as_its_date() -> None:
    assert probe._date("2026-12-18T16:00:00Z") == date(2026, 12, 18)
    assert probe._date("2026-12-18T00:00:00+00:00") == date(2026, 12, 18)
    assert probe._date("2026-12-18") == date(2026, 12, 18)
    assert probe._date("") is None


def test_shown_scopes_mask_account_numbers() -> None:
    shown = probe.shown_scopes(frozenset({"read", "accounts:5wt12345:owner", "accounts:5wt99999:trade-only", "accounts:x"}))
    assert shown == ["accounts:***", "accounts:***:owner", "accounts:***:trade-only", "read"]


def test_a_quote_time_without_a_zone_is_not_aged() -> None:
    assert probe.age_seconds("2026-11-16T15:00:00", NOW) is None


async def test_a_malformed_expiry_doesnt_cost_the_other_sections(monkeypatch: pytest.MonkeyPatch, run: list[str]) -> None:
    async def one_bad_date(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        if path == "/option-chains/SPY/nested":
            return {"data": {"items": [{"expirations": [
                {"expiration-date": "", "strikes": STRIKES},
                {"expiration-date": EXPIRY, "strikes": STRIKES},
            ]}]}}
        return await fake_get(path, params, op=op)

    monkeypatch.setattr(tt, "get", one_bad_date)
    await probe.main(run.append)
    report = "\n".join(run)
    assert "11 of 11 quotes came back" in report
    assert "Summary for a near-money call" in report
    assert "failed" not in report
