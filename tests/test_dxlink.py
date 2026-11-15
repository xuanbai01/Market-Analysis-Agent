"""DXLink, tastytrade's market-data websocket (ADR 0009), against a fake
server that speaks the documented handshake: SETUP, AUTH_STATE, AUTH,
CHANNEL_REQUEST/OPENED, FEED_SETUP/CONFIG, FEED_SUBSCRIPTION, FEED_DATA."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest
from websockets.asyncio.client import connect as real_connect
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response

from app.services import dxlink
from app.services import tastytrade_client as tt

QUOTE_TOKEN = "qt-test-dxlink-token"
CANDLE_FIELDS = list(dxlink.CANDLE_FIELDS)


def _ms(day: str) -> int:
    return int(datetime.fromisoformat(day).replace(tzinfo=UTC).timestamp() * 1000)


def candle_row(symbol: str, day: str, close: float, flags: int = 0, iv: Any = "NaN") -> list[Any]:
    values = {
        "eventType": "Candle", "eventSymbol": symbol, "time": _ms(day), "eventFlags": flags,
        "open": close - 1, "high": close + 1, "low": close - 2, "close": close,
        "volume": 1000.0, "impVolatility": iv, "openInterest": "NaN",
    }
    return [values[name] for name in CANDLE_FIELDS]


class FakeServer:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.inbox: asyncio.Queue[str] = asyncio.Queue()
        self.authorize = True
        self.feed_fields: dict[str, list[str]] | None = None  # FEED_CONFIG's eventFields
        self.on_subscribe: list[list[Any]] = []  # each a FEED_DATA ``data`` list
        self.connected_to: list[str] = []
        self.open_sessions = 0
        self.max_open_sessions = 0
        self.options: dict[str, Any] = {}
        self.close_delay = 0.0
        self.error: Any = None  # sent as an ERROR message in answer to AUTH

    def reply(self, message: dict[str, Any]) -> None:
        self.inbox.put_nowait(json.dumps(message))

    async def send(self, text: str) -> None:
        message = json.loads(text)
        self.sent.append(message)
        kind = message["type"]
        if kind == "SETUP":
            self.reply({"type": "SETUP", "channel": 0, "keepaliveTimeout": 60, "version": "1.0-test"})
            self.reply({"type": "AUTH_STATE", "channel": 0, "state": "UNAUTHORIZED"})
        elif kind == "AUTH" and self.error is not None:
            self.reply({"type": "ERROR", "channel": 0, "error": self.error, "message": f"bad token {message['token']}"})
        elif kind == "AUTH":
            state = "AUTHORIZED" if self.authorize and message["token"] == QUOTE_TOKEN else "UNAUTHORIZED"
            self.reply({"type": "AUTH_STATE", "channel": 0, "state": state, "userId": "u1"})
        elif kind == "CHANNEL_REQUEST":
            self.reply({"type": "CHANNEL_OPENED", "channel": message["channel"], "service": "FEED"})
        elif kind == "FEED_SETUP":
            self.reply({"type": "KEEPALIVE", "channel": 0})
            config: dict[str, Any] = {"type": "FEED_CONFIG", "channel": message["channel"], "dataFormat": "COMPACT"}
            if self.feed_fields is not None:
                config["eventFields"] = self.feed_fields
            self.reply(config)
        elif kind == "FEED_SUBSCRIPTION":
            for data in self.on_subscribe:
                self.reply({"type": "FEED_DATA", "channel": message["channel"], "data": data})

    async def recv(self) -> str:
        return await self.inbox.get()

    def connect(self, url: str, **options: Any) -> Any:
        server = self
        server.options = options

        @asynccontextmanager
        async def session() -> Any:
            server.connected_to.append(url)
            server.open_sessions += 1
            server.max_open_sessions = max(server.max_open_sessions, server.open_sessions)
            try:
                yield server
            finally:
                server.open_sessions -= 1
                if server.close_delay:
                    await asyncio.sleep(server.close_delay)

        return session()

    def subscriptions(self) -> list[dict[str, Any]]:
        return [item for m in self.sent if m["type"] == "FEED_SUBSCRIPTION" for item in m.get("add", [])]


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> FakeServer:
    fake = FakeServer()
    monkeypatch.setattr(dxlink, "_connect", fake.connect)
    monkeypatch.setattr(dxlink, "IDLE_SECONDS", 0.05)
    monkeypatch.setattr(dxlink, "FETCH_TIMEOUT_SECONDS", 1.0)
    return fake


@pytest.fixture(autouse=True)
def quote_tokens(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    async def fake_get(path: str, params: Any = None, *, op: str) -> dict[str, Any]:
        calls.append(path)
        return {"data": {"token": QUOTE_TOKEN, "dxlink-url": "wss://tasty-openapi-ws.dxfeed.com/realtime", "level": "api"}}

    monkeypatch.setattr(tt, "get", fake_get)
    dxlink.reset()
    yield calls
    dxlink.reset()


async def test_quote_token_is_read_once_and_cached(quote_tokens: list[str]) -> None:
    first = await dxlink.quote_token()
    second = await dxlink.quote_token()
    assert first == second == dxlink.QuoteToken(QUOTE_TOKEN, "wss://tasty-openapi-ws.dxfeed.com/realtime", "api")
    assert quote_tokens == ["/api-quote-tokens"]


@pytest.mark.parametrize(
    "url",
    [
        "ws://tasty-openapi-ws.dxfeed.com/realtime",  # no TLS
        "wss://evil.example/realtime",
        "wss://dxfeed.com.evil.example/realtime",
        "wss://notdxfeed.com/realtime",
        "https://tasty-openapi-ws.dxfeed.com/realtime",
        "wss://169.254.169.254/realtime",
        "wss://other.dxfeed.com/realtime",  # a dxFeed host, but not tastytrade's feed
        "wss://tasty-openapi-ws.dxfeed.com:22/realtime",
        "wss://u:p@tasty-openapi-ws.dxfeed.com/realtime",
        "wss://tasty-openapi-ws.dxfeed.com/realtime?token=abc",
        "wss://tasty-openapi-ws.dxfeed.com/realtime#x",
        "wss://localhost\x00.tasty-openapi-ws.dxfeed.com/realtime",
        "wss://evil.example\uff0e.tasty-openapi-ws.dxfeed.com/realtime",
        "wss://tasty-openapi-ws.dxfeed.com:notaport/realtime",
        "wss://[zz]/realtime",
        "wss://tasty-openapi-ws..dxfeed.com/realtime",  # an empty label
        "wss://[::1]/realtime",
    ],
)
async def test_a_feed_address_off_dxfeed_is_refused(
    monkeypatch: pytest.MonkeyPatch, server: FakeServer, url: str
) -> None:
    async def fake_get(path: str, params: Any = None, *, op: str) -> dict[str, Any]:
        return {"data": {"token": QUOTE_TOKEN, "dxlink-url": url, "level": "api"}}

    monkeypatch.setattr(tt, "get", fake_get)
    with pytest.raises(dxlink.DxlinkError, match="dxFeed"):
        await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert server.connected_to == []


async def test_handshake_follows_the_documented_order(server: FakeServer) -> None:
    server.on_subscribe = [["Candle", candle_row("SPY{=1d}", "2026-11-13", 600.0, flags=dxlink.SNAPSHOT_END)]]
    await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))

    kinds = [m["type"] for m in server.sent]
    assert kinds == ["SETUP", "AUTH", "CHANNEL_REQUEST", "FEED_SETUP", "FEED_SUBSCRIPTION"]
    auth = server.sent[1]
    assert auth == {"type": "AUTH", "channel": 0, "token": QUOTE_TOKEN}
    setup = server.sent[3]
    assert setup["acceptDataFormat"] == "COMPACT"
    assert setup["acceptEventFields"] == {"Candle": CANDLE_FIELDS}
    assert server.connected_to == ["wss://tasty-openapi-ws.dxfeed.com/realtime"]


async def test_candles_come_back_oldest_first_until_the_snapshot_ends(server: FakeServer) -> None:
    sym = "SPY{=1d}"
    # dxFeed sends a history snapshot newest first; the last row carries SNAPSHOT_END.
    server.on_subscribe = [
        ["Candle", candle_row(sym, "2026-11-13", 603.0, flags=dxlink.SNAPSHOT_BEGIN) + candle_row(sym, "2026-11-12", 602.0)],
        ["Candle", candle_row(sym, "2026-11-11", 601.0, iv=0.18) + candle_row(sym, "2026-11-10", 600.0, flags=dxlink.SNAPSHOT_END)],
        ["Candle", candle_row(sym, "2026-11-13", 604.0)],  # a live update after the snapshot: not read
    ]
    history = await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 10, tzinfo=UTC))

    assert history.complete is True
    assert [c.time.date().isoformat() for c in history.candles] == ["2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"]
    assert [c.close for c in history.candles] == [600.0, 601.0, 602.0, 603.0]
    assert history.candles[1].imp_volatility == 0.18
    assert history.candles[0].imp_volatility is None  # "NaN"
    assert history.candles[0].open_interest is None
    sub = server.subscriptions()
    assert sub == [{"type": "Candle", "symbol": "SPY{=1d}", "fromTime": int(datetime(2026, 11, 10, tzinfo=UTC).timestamp())}]


async def test_from_time_can_be_sent_in_milliseconds(server: FakeServer) -> None:
    server.on_subscribe = [["Candle", candle_row("SPY{=1d}", "2026-11-13", 600.0, flags=dxlink.SNAPSHOT_END)]]
    start = datetime(2026, 11, 1, tzinfo=UTC)
    await dxlink.fetch_candles("SPY", "1d", start, time_unit_ms=True)
    assert server.subscriptions()[0]["fromTime"] == int(start.timestamp() * 1000)


async def test_removed_rows_are_dropped(server: FakeServer) -> None:
    sym = "SPY{=1d}"
    server.on_subscribe = [
        ["Candle", candle_row(sym, "2026-11-13", 603.0) + candle_row(sym, "2026-11-12", 602.0, flags=dxlink.REMOVE_EVENT | dxlink.SNAPSHOT_END)],
    ]
    history = await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert [c.close for c in history.candles] == [603.0]
    assert history.complete is True


async def test_the_servers_field_order_wins(server: FakeServer) -> None:
    reordered = ["eventSymbol", "eventType", "close", "time", "eventFlags"]
    server.feed_fields = {"Candle": reordered}
    server.on_subscribe = [["Candle", ["SPY{=1d}", "Candle", 600.5, _ms("2026-11-13"), dxlink.SNAPSHOT_END]]]
    history = await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert [(c.time.date().isoformat(), c.close, c.open) for c in history.candles] == [("2026-11-13", 600.5, None)]


async def test_a_history_that_never_ends_comes_back_incomplete(server: FakeServer) -> None:
    server.on_subscribe = [["Candle", candle_row("SPY{=1d}", "2026-11-13", 600.0)]]
    history = await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert history.complete is False
    assert [c.close for c in history.candles] == [600.0]


async def test_no_candles_at_all_is_an_empty_incomplete_history(server: FakeServer) -> None:
    history = await dxlink.fetch_candles("ZZZZ", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert history == dxlink.CandleHistory(candles=(), complete=False)


async def test_a_refused_quote_token_is_forgotten(server: FakeServer, quote_tokens: list[str]) -> None:
    server.authorize = False
    with pytest.raises(dxlink.DxlinkError, match="refused"):
        await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    server.authorize = True
    server.on_subscribe = [["Candle", candle_row("SPY{=1d}", "2026-11-13", 600.0, flags=dxlink.SNAPSHOT_END)]]
    await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert quote_tokens == ["/api-quote-tokens", "/api-quote-tokens"]


async def test_a_server_that_goes_quiet_times_out(monkeypatch: pytest.MonkeyPatch, server: FakeServer) -> None:
    async def never_answers(text: str) -> None:
        server.sent.append(json.loads(text))

    monkeypatch.setattr(server, "send", never_answers)
    monkeypatch.setattr(dxlink, "FETCH_TIMEOUT_SECONDS", 0.1)
    with pytest.raises(dxlink.DxlinkError, match="timed out"):
        await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))


async def test_fetch_once_reads_one_event_per_symbol(server: FakeServer) -> None:
    fields = list(dxlink.SUMMARY_FIELDS)

    def summary(symbol: str, oi: Any) -> list[Any]:
        row = {"eventType": "Summary", "eventSymbol": symbol, "openInterest": oi, "dayOpenPrice": 1.0,
               "dayHighPrice": 1.2, "dayLowPrice": 0.9, "prevDayClosePrice": 1.1}
        return [row[name] for name in fields]

    server.on_subscribe = [["Summary", summary(".SPY261218C600", 1234) + summary(".SPY261218P600", "NaN")]]
    events = await dxlink.fetch_once("Summary", [".SPY261218C600", ".SPY261218P600"])
    assert events[".SPY261218C600"]["openInterest"] == 1234
    assert events[".SPY261218P600"]["openInterest"] is None
    assert {s["symbol"] for s in server.subscriptions()} == {".SPY261218C600", ".SPY261218P600"}
    assert all("fromTime" not in s for s in server.subscriptions())


async def test_one_session_at_a_time(server: FakeServer) -> None:
    server.on_subscribe = [["Candle", candle_row("SPY{=1d}", "2026-11-13", 600.0, flags=dxlink.SNAPSHOT_END)]]
    start = datetime(2026, 11, 1, tzinfo=UTC)
    await asyncio.gather(*(dxlink.fetch_candles("SPY", "1d", start) for _ in range(3)))
    assert server.max_open_sessions == 1


async def test_logs_hold_no_quote_token(server: FakeServer, caplog: pytest.LogCaptureFixture) -> None:
    server.on_subscribe = [["Candle", candle_row("SPY{=1d}", "2026-11-13", 600.0, flags=dxlink.SNAPSHOT_END)]]
    with caplog.at_level(logging.DEBUG, logger="app"):
        await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
        server.authorize = False
        dxlink.reset()
        with pytest.raises(dxlink.DxlinkError):
            await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert any(getattr(r, "service_id", "") == "dxlink.candles" for r in caplog.records)
    for record in (r for r in caplog.records if r.name.startswith("app")):
        text = record.getMessage() + str(getattr(record, "input_summary", "")) + str(getattr(record, "output_summary", ""))
        if record.exc_info:
            text += logging.Formatter().formatException(record.exc_info)
        assert QUOTE_TOKEN not in text


def test_the_feed_address_of_tastytrade_is_accepted() -> None:
    assert dxlink.is_feed_url("wss://tasty-openapi-ws.dxfeed.com/realtime")
    assert dxlink.is_feed_url("wss://tasty-openapi-ws.dxfeed.com:443/realtime")
    assert dxlink.is_feed_url("wss://TASTY-OPENAPI-WS.DXFEED.COM/realtime")  # hostnames compare lowercased
    assert dxlink.is_feed_url("wss://tasty-openapi-dxlink-md-ws.dxfeed.com/realtime")  # what the account was given
    assert not dxlink.is_feed_url("wss://tasty-openapi-dxlink-md-ws.dxfeed.com.evil.example/realtime")


def test_a_redirect_is_never_followed() -> None:
    redirect = InvalidStatus(Response(302, "Found", Headers({"Location": "wss://evil.example/steal"}), b""))
    url = "wss://tasty-openapi-ws.dxfeed.com/realtime"
    assert real_connect(url).process_redirect(redirect) == "wss://evil.example/steal"  # websockets would follow it
    assert dxlink._NoRedirects(url).process_redirect(redirect) is redirect
    assert dxlink._connect is dxlink._NoRedirects


async def test_the_session_is_capped_uncompressed_and_quiet_in_the_logs(server: FakeServer) -> None:
    server.on_subscribe = [["Candle", candle_row("SPY{=1d}", "2026-11-13", 600.0, flags=dxlink.SNAPSHOT_END)]]
    await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    options = server.options
    assert options["compression"] is None
    assert options["max_size"] <= 4 * 1024 * 1024
    assert options["max_queue"] <= 4
    assert options["logger"].getEffectiveLevel() >= logging.WARNING
    assert not options["logger"].isEnabledFor(logging.DEBUG)


def test_the_quote_tokens_repr_hides_it() -> None:
    token = dxlink.QuoteToken(QUOTE_TOKEN, "wss://tasty-openapi-ws.dxfeed.com/realtime", "api")
    assert QUOTE_TOKEN not in repr(token)


@pytest.mark.parametrize(("code", "shown"), [("UNAUTHORIZED", "UNAUTHORIZED"), ("invalid token: qt-test-dxlink-token\nINFO forged", "unknown"), ({"x": 1}, "unknown")])
async def test_a_dxlink_error_shows_only_a_known_code(server: FakeServer, code: Any, shown: str) -> None:
    server.error = code
    with pytest.raises(dxlink.DxlinkError) as raised:
        await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert str(raised.value) == f"DXLink error: {shown}"
    assert QUOTE_TOKEN not in str(raised.value)


async def test_malformed_messages_and_rows_are_skipped(server: FakeServer) -> None:
    sym = "SPY{=1d}"
    bad_time = candle_row(sym, "2026-11-12", 602.0)
    bad_time[CANDLE_FIELDS.index("time")] = 1e20
    server.on_subscribe = [
        {"not": "a list"},
        7,
        ["Candle", {"not": "a list"}],
        [["Candle"], 3, "x"],
        ["Candle", bad_time + candle_row(sym, "2026-11-13", 603.0, flags=dxlink.SNAPSHOT_END)],
    ]
    server.inbox.put_nowait("not json")
    history = await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert [c.close for c in history.candles] == [603.0]
    assert history.complete is True


async def test_a_message_that_isnt_an_object_is_skipped_in_the_handshake(server: FakeServer) -> None:
    server.inbox.put_nowait("[1, 2, 3]")
    server.inbox.put_nowait('"text"')
    server.on_subscribe = [["Candle", candle_row("SPY{=1d}", "2026-11-13", 600.0, flags=dxlink.SNAPSHOT_END)]]
    history = await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert history.complete is True


async def test_odd_field_names_from_the_server_fall_back_to_ours(server: FakeServer) -> None:
    server.feed_fields = {"Candle": [["nested"], 3]}
    server.on_subscribe = [["Candle", candle_row("SPY{=1d}", "2026-11-13", 600.0, flags=dxlink.SNAPSHOT_END)]]
    history = await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert [c.close for c in history.candles] == [600.0]


async def test_a_history_past_the_cap_stops_short(monkeypatch: pytest.MonkeyPatch, server: FakeServer) -> None:
    monkeypatch.setattr(dxlink, "MAX_CANDLES", 2)
    sym = "SPY{=1d}"
    rows = candle_row(sym, "2026-11-13", 603.0) + candle_row(sym, "2026-11-12", 602.0) + candle_row(sym, "2026-11-11", 601.0, flags=dxlink.SNAPSHOT_END)
    server.on_subscribe = [["Candle", rows]]
    history = await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert len(history.candles) == 2
    assert history.complete is False


async def test_too_many_events_stop_the_fetch(monkeypatch: pytest.MonkeyPatch, server: FakeServer) -> None:
    monkeypatch.setattr(dxlink, "MAX_EVENTS", 3)
    rows = sum((candle_row("OTHER{=1d}", "2026-11-13", 1.0) for _ in range(5)), [])
    server.on_subscribe = [["Candle", rows]]
    history = await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert history == dxlink.CandleHistory(candles=(), complete=False)


async def test_an_unexpected_failure_names_only_its_type(monkeypatch: pytest.MonkeyPatch, server: FakeServer) -> None:
    async def breaks(text: str) -> None:
        raise ConnectionResetError(f"peer said {QUOTE_TOKEN}")

    monkeypatch.setattr(server, "send", breaks)
    with pytest.raises(dxlink.DxlinkError) as raised:
        await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert str(raised.value) == "the DXLink session failed (ConnectionResetError)"


async def test_a_slow_close_keeps_a_complete_history(monkeypatch: pytest.MonkeyPatch, server: FakeServer) -> None:
    monkeypatch.setattr(dxlink, "FETCH_TIMEOUT_SECONDS", 0.2)
    server.close_delay = 0.5
    server.on_subscribe = [["Candle", candle_row("SPY{=1d}", "2026-11-13", 600.0, flags=dxlink.SNAPSHOT_END)]]
    history = await dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC))
    assert history.complete is True


async def test_a_feed_that_never_goes_quiet_still_ends(monkeypatch: pytest.MonkeyPatch, server: FakeServer) -> None:
    monkeypatch.setattr(dxlink, "FETCH_TIMEOUT_SECONDS", 0.3)

    async def chatty() -> None:
        for _ in range(200):
            server.reply({"type": "FEED_DATA", "channel": 3, "data": ["Candle", candle_row("SPY{=1d}", "2026-11-13", 600.0)]})
            await asyncio.sleep(0.01)

    task = asyncio.create_task(chatty())
    try:
        history = await asyncio.wait_for(dxlink.fetch_candles("SPY", "1d", datetime(2026, 11, 1, tzinfo=UTC)), 2.0)
    finally:
        task.cancel()
    assert history.complete is False


async def test_a_history_the_server_cut_short_is_not_complete(server: FakeServer) -> None:
    sym = "SPY{=1d}"
    server.on_subscribe = [
        ["Candle", candle_row(sym, "2026-11-13", 603.0) + candle_row(sym, "2026-11-12", 602.0, flags=dxlink.SNAPSHOT_SNIP)],
    ]
    history = await dxlink.fetch_candles("SPY", "1d", datetime(2005, 1, 1, tzinfo=UTC))
    assert [c.close for c in history.candles] == [602.0, 603.0]
    assert history.complete is False
    assert history.snipped is True
