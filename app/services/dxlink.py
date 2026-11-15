"""
DXLink, tastytrade's market-data websocket (dxFeed's protocol), for what
the REST API doesn't serve: candle history, open interest (Summary) and
dxFeed's Greeks (ADR 0009).

A session is opened for one fetch and closed: SETUP, AUTH with a quote
token from ``/api-quote-tokens`` (valid 24 hours, cached 23), a FEED
channel, FEED_SETUP in the COMPACT format, then FEED_SUBSCRIPTION. A fetch
lasts at most ``FETCH_TIMEOUT_SECONDS``, under the server's 60-second
keepalive timeout, so no keepalive is sent. One session at a time per
machine (tastytrade allows five).

A candle history arrives newest first, the last row flagged
``SNAPSHOT_END`` (or ``SNAPSHOT_SNIP`` when the server cut it short);
live updates follow and are not read. tastytrade documents ``fromTime``
in seconds and dxFeed's own APIs take milliseconds, so
``fetch_candles`` sends seconds unless told otherwise; the probe
(``tastytrade_probe``) checks which one DXLink honours.

The quote token is a credential: it is never logged. What comes back is
tastytrade's data: callers keep it in memory and never store it or put it
in a prompt.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from websockets.asyncio.client import connect as _ws_connect

from app.core.observability import log_external_call
from app.services import tastytrade_client as tt

QUOTE_TOKEN_TTL_SECONDS = 23 * 3600
FETCH_TIMEOUT_SECONDS = 20.0
# Once events have come, a feed this quiet has sent all it will.
IDLE_SECONDS = 3.0
OPEN_TIMEOUT_SECONDS = 10.0
MAX_MESSAGE_BYTES = 16 * 1024 * 1024
# tastytrade's DXLink feed (tasty-openapi-ws.dxfeed.com); the address comes
# with the quote token, and nothing else is connected to.
FEED_DOMAIN = "dxfeed.com"
_CHANNEL = 3
_SETUP = {
    "type": "SETUP",
    "channel": 0,
    "version": "0.1-DXF-JS/0.3.0",
    "keepaliveTimeout": 60,
    "acceptKeepaliveTimeout": 60,
}

# dxFeed's eventFlags.
REMOVE_EVENT = 0x02
SNAPSHOT_BEGIN = 0x04
SNAPSHOT_END = 0x08
SNAPSHOT_SNIP = 0x10

CANDLE_FIELDS = (
    "eventType", "eventSymbol", "time", "eventFlags",
    "open", "high", "low", "close", "volume", "impVolatility", "openInterest",
)
SUMMARY_FIELDS = (
    "eventType", "eventSymbol", "openInterest", "dayOpenPrice", "dayHighPrice", "dayLowPrice", "prevDayClosePrice",
)
GREEKS_FIELDS = ("eventType", "eventSymbol", "price", "volatility", "delta", "gamma", "theta", "rho", "vega")
QUOTE_FIELDS = ("eventType", "eventSymbol", "bidPrice", "askPrice", "bidSize", "askSize", "bidTime", "askTime")
_FIELDS = {"Candle": CANDLE_FIELDS, "Summary": SUMMARY_FIELDS, "Greeks": GREEKS_FIELDS, "Quote": QUOTE_FIELDS}
_TEXT_FIELDS = frozenset({"eventType", "eventSymbol"})


class DxlinkError(Exception):
    """The session couldn't be set up: a refused token, an error, a timeout."""


@dataclass(frozen=True)
class QuoteToken:
    token: str
    url: str
    level: str  # "api" for the account's own feed; "demo" comes with a /delayed URL


@dataclass(frozen=True)
class Candle:
    time: datetime  # UTC, the candle's start
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: float | None
    imp_volatility: float | None
    open_interest: float | None


@dataclass(frozen=True)
class CandleHistory:
    candles: tuple[Candle, ...]  # oldest first
    complete: bool  # the server marked the snapshot's end


# Swapped in tests.
_connect: Callable[..., Any] = _ws_connect
_clock = time.monotonic

_quote: tuple[QuoteToken, float] | None = None
_session_lock: asyncio.Lock | None = None


def reset() -> None:
    global _quote, _session_lock
    _quote, _session_lock = None, None


def _lock() -> asyncio.Lock:
    global _session_lock
    if _session_lock is None:
        _session_lock = asyncio.Lock()
    return _session_lock


async def quote_token() -> QuoteToken:
    """The DXLink token and address for the owner's account, cached 23 hours."""
    global _quote
    if _quote is not None and _quote[1] > _clock():
        return _quote[0]
    payload = await tt.get("/api-quote-tokens", op="api_quote_token")
    data = payload.get("data") or {}
    try:
        token = QuoteToken(token=str(data["token"]), url=str(data["dxlink-url"]), level=str(data.get("level") or ""))
    except KeyError as exc:
        raise DxlinkError(f"the quote token answer has no {exc.args[0]}") from None
    if not _is_feed_url(token.url):
        raise DxlinkError("the quote token's feed address is not a dxFeed websocket")
    _quote = (token, _clock() + QUOTE_TOKEN_TTL_SECONDS)
    return token


def _is_feed_url(url: str) -> bool:
    """The server connects where tastytrade's answer says, so only to a
    dxFeed websocket over TLS."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "wss" and (host == FEED_DOMAIN or host.endswith("." + FEED_DOMAIN))


def _forget_quote_token() -> None:
    global _quote
    _quote = None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _events(data: list[Any], event_type: str, fields: Sequence[str]) -> Iterator[dict[str, Any]]:
    """The ``event_type`` events in a COMPACT ``data`` list: alternating
    event types and flat value arrays, ``len(fields)`` values per event."""
    pairs = data if data and isinstance(data[0], list) else [data[i : i + 2] for i in range(0, len(data), 2)]
    width = len(fields)
    for pair in pairs:
        if len(pair) != 2 or pair[0] != event_type or not isinstance(pair[1], list):
            continue
        values = pair[1]
        for start in range(0, len(values) - width + 1, width):
            row = dict(zip(fields, values[start : start + width], strict=True))
            yield {name: value if name in _TEXT_FIELDS else _number(value) for name, value in row.items()}


async def _send(ws: Any, message: dict[str, Any]) -> None:
    await ws.send(json.dumps(message))


async def _expect(ws: Any, kind: str) -> dict[str, Any]:
    while True:
        message = json.loads(await ws.recv())
        if message.get("type") == "ERROR":
            raise DxlinkError(f"DXLink error: {message.get('error') or 'unknown'}")
        if message.get("type") == kind:
            return message


async def _open_feed(ws: Any, token: QuoteToken, event_type: str) -> list[str]:
    """The handshake; returns the fields the server will send, in its order."""
    await _send(ws, _SETUP)
    await _expect(ws, "AUTH_STATE")  # UNAUTHORIZED, before AUTH
    await _send(ws, {"type": "AUTH", "channel": 0, "token": token.token})
    state = await _expect(ws, "AUTH_STATE")
    if state.get("state") != "AUTHORIZED":
        _forget_quote_token()
        raise DxlinkError("DXLink refused the quote token")
    await _send(ws, {"type": "CHANNEL_REQUEST", "channel": _CHANNEL, "service": "FEED", "parameters": {"contract": "AUTO"}})
    await _expect(ws, "CHANNEL_OPENED")
    wanted = list(_FIELDS[event_type])
    await _send(ws, {
        "type": "FEED_SETUP",
        "channel": _CHANNEL,
        "acceptAggregationPeriod": 0.1,
        "acceptDataFormat": "COMPACT",
        "acceptEventFields": {event_type: wanted},
    })
    config = await _expect(ws, "FEED_CONFIG")
    return list((config.get("eventFields") or {}).get(event_type) or wanted)


async def _run(
    event_type: str, subscriptions: list[dict[str, Any]], on_event: Callable[[dict[str, Any]], bool]
) -> bool:
    """Opens a session, subscribes, and hands each ``event_type`` event to
    ``on_event`` until it returns True (then True). False when the feed
    went quiet after some events or the time ran out after subscribing.
    ``DxlinkError`` when the session couldn't be set up in time."""
    async with _lock():
        token = await quote_token()
        subscribed = False
        try:
            async with asyncio.timeout(FETCH_TIMEOUT_SECONDS):
                async with _connect(token.url, open_timeout=OPEN_TIMEOUT_SECONDS, max_size=MAX_MESSAGE_BYTES) as ws:
                    fields = await _open_feed(ws, token, event_type)
                    await _send(ws, {"type": "FEED_SUBSCRIPTION", "channel": _CHANNEL, "reset": True, "add": subscriptions})
                    subscribed = True
                    seen = False
                    while True:
                        try:
                            raw = await (asyncio.wait_for(ws.recv(), IDLE_SECONDS) if seen else ws.recv())
                        except TimeoutError:  # quiet after events (wait_for's own timeout)
                            return False
                        message = json.loads(raw)
                        if message.get("type") == "ERROR":
                            raise DxlinkError(f"DXLink error: {message.get('error') or 'unknown'}")
                        if message.get("type") != "FEED_DATA":
                            continue
                        for event in _events(message.get("data") or [], event_type, fields):
                            seen = True
                            if on_event(event):
                                return True
        except TimeoutError:
            if not subscribed:
                raise DxlinkError("DXLink timed out before the feed opened") from None
            return False


def _candle(event: dict[str, Any]) -> Candle | None:
    millis = event.get("time")
    if millis is None:
        return None
    return Candle(
        time=datetime.fromtimestamp(millis / 1000, tz=UTC),
        open=event.get("open"),
        high=event.get("high"),
        low=event.get("low"),
        close=event.get("close"),
        volume=event.get("volume"),
        imp_volatility=event.get("impVolatility"),
        open_interest=event.get("openInterest"),
    )


async def fetch_candles(symbol: str, period: str, from_time: datetime, *, time_unit_ms: bool = False) -> CandleHistory:
    """``symbol``'s candles of ``period`` (dxFeed's codes: ``1d``, ``1h``,
    ``5m``) from ``from_time``, oldest first. ``symbol`` is a streamer
    symbol (an option's comes from the chain's ``streamer-symbol``)."""
    candle_symbol = f"{symbol}{{={period}}}"
    stamp = from_time.timestamp()
    from_value = int(stamp * 1000) if time_unit_ms else int(stamp)
    by_time: dict[datetime, Candle] = {}

    def on_event(event: dict[str, Any]) -> bool:
        if event.get("eventSymbol") != candle_symbol:
            return False
        flags = int(event.get("eventFlags") or 0)
        candle = _candle(event)
        if candle is not None and not flags & REMOVE_EVENT:
            by_time[candle.time] = candle
        return bool(flags & (SNAPSHOT_END | SNAPSHOT_SNIP))

    summary = {"symbol": candle_symbol, "from": from_time.date().isoformat(), "unit": "ms" if time_unit_ms else "s"}
    with log_external_call("dxlink.candles", summary) as call:
        complete = await _run("Candle", [{"type": "Candle", "symbol": candle_symbol, "fromTime": from_value}], on_event)
        call.record_output({"candles": len(by_time), "complete": complete})
    return CandleHistory(candles=tuple(by_time[t] for t in sorted(by_time)), complete=complete)


async def fetch_once(event_type: str, symbols: Sequence[str]) -> dict[str, dict[str, Any]]:
    """The first ``event_type`` event (Summary, Greeks, Quote) for each of
    ``symbols``, by symbol; a symbol that sent none is missing."""
    wanted = set(symbols)
    found: dict[str, dict[str, Any]] = {}

    def on_event(event: dict[str, Any]) -> bool:
        symbol = event.get("eventSymbol")
        if symbol in wanted and symbol not in found:
            found[symbol] = event
        return len(found) == len(wanted)

    with log_external_call(f"dxlink.{event_type.lower()}", {"symbols": len(wanted)}) as call:
        await _run(event_type, [{"type": event_type, "symbol": s} for s in sorted(wanted)], on_event)
        call.record_output({"events": len(found)})
    return found
