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

    def reply(self, message: dict[str, Any]) -> None:
        self.inbox.put_nowait(json.dumps(message))

    async def send(self, text: str) -> None:
        message = json.loads(text)
        self.sent.append(message)
        kind = message["type"]
        if kind == "SETUP":
            self.reply({"type": "SETUP", "channel": 0, "keepaliveTimeout": 60, "version": "1.0-test"})
            self.reply({"type": "AUTH_STATE", "channel": 0, "state": "UNAUTHORIZED"})
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

    def connect(self, url: str, **_: Any) -> Any:
        server = self

        @asynccontextmanager
        async def session() -> Any:
            server.connected_to.append(url)
            server.open_sessions += 1
            server.max_open_sessions = max(server.max_open_sessions, server.open_sessions)
            try:
                yield server
            finally:
                server.open_sessions -= 1

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
