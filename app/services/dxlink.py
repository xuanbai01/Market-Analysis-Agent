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
``SNAPSHOT_END``, or ``SNAPSHOT_SNIP`` when the server cut it short (then
the history is ``snipped`` and not ``complete``); live updates follow and
are not read. Two things the probe found that the docs don't say
(2026-11-15):
- ``fromTime`` is in milliseconds. tastytrade's docs say seconds, but a
  value in seconds reads as January 1970 and returns everything.
- The server echoes the candle symbol in its normal form: ``SPY{=1d}``
  comes back as ``SPY{=d}``. A session subscribes to one candle symbol, so
  its events are matched on the symbol and the ``{=`` that follows it.
A history holds at most 8,000 candles: SPY's daily ones reach back to
1995, its 5-minute ones about six weeks.

The server is trusted as little as the feed allows:
- the address, which comes in tastytrade's answer, must be tastytrade's
  feed host over TLS on 443, and a redirect is never followed;
- messages are capped at 4 MiB and not compressed (no decompression bomb);
- a fetch keeps at most ``MAX_EVENTS`` events and ``MAX_CANDLES`` candles;
- a malformed message or row is skipped;
- anything unexpected surfaces as a ``DxlinkError`` naming its type, never
  the server's text.

The quote token is a credential: it is never logged (its repr hides it,
and websockets' own frame log is held at WARNING). What comes back is
tastytrade's data: callers keep it in memory and never store it or put
it in a prompt.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
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
MAX_MESSAGE_BYTES = 4 * 1024 * 1024
MAX_QUEUE = 4
MAX_EVENTS = 100_000
MAX_CANDLES = 20_000
# tastytrade's DXLink feeds. The address comes with the quote token, and
# nothing else is connected to. The docs name the first; the owner's
# account was given the second (the probe, 2026-11-15).
FEED_HOSTS = frozenset({"tasty-openapi-ws.dxfeed.com", "tasty-openapi-dxlink-md-ws.dxfeed.com"})
_CHANNEL = 3
_SETUP = {
    "type": "SETUP",
    "channel": 0,
    "version": "0.1-DXF-JS/0.3.0",
    "keepaliveTimeout": 60,
    "acceptKeepaliveTimeout": 60,
}
# DXLink's error codes; any other text from the server is not repeated.
_ERROR_CODES = frozenset({"UNSUPPORTED_PROTOCOL", "TIMEOUT", "UNAUTHORIZED", "INVALID_MESSAGE", "BAD_ACTION", "UNKNOWN"})
_HOSTNAME = re.compile(r"[a-z0-9.-]+")

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

# websockets logs every frame, the AUTH frame and its token included, at
# DEBUG; this logger never lets that through, whatever the root's level.
_WS_LOGGER = logging.getLogger("websockets.dxlink")
_WS_LOGGER.setLevel(logging.WARNING)


class DxlinkError(Exception):
    """The session couldn't be set up or failed: a refused token, an error, a timeout."""


@dataclass(frozen=True)
class QuoteToken:
    token: str = field(repr=False)
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
    complete: bool  # the server marked the snapshot's end (SNAPSHOT_END)
    snipped: bool = False  # the server cut the history short (SNAPSHOT_SNIP)


class _NoRedirects(_ws_connect):
    """websockets' connect, following no redirect: the address was checked,
    and a redirect could carry the quote token to another host."""

    def process_redirect(self, exc: Exception) -> Exception | str:
        return exc


# Swapped in tests.
_connect: Callable[..., Any] = _NoRedirects
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


def is_feed_url(url: str) -> bool:
    """Only tastytrade's feed host, over TLS on 443, with no credentials,
    query or fragment in the address."""
    try:
        parts = urlsplit(url)
        port = parts.port
        host = parts.hostname or ""
    except ValueError:
        return False
    return (
        parts.scheme == "wss"
        and _HOSTNAME.fullmatch(host) is not None
        and host in FEED_HOSTS
        and port in (None, 443)
        and parts.username is None
        and parts.password is None
        and not parts.query
        and not parts.fragment
    )


async def quote_token() -> QuoteToken:
    """The DXLink token and address for the owner's account, cached 23 hours."""
    global _quote
    if _quote is not None and _quote[1] > _clock():
        return _quote[0]
    payload = await tt.get("/api-quote-tokens", op="api_quote_token")
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not all(isinstance(data.get(k), str) for k in ("token", "dxlink-url")):
        raise DxlinkError("the quote token answer is missing its token or address")
    token = QuoteToken(token=data["token"], url=data["dxlink-url"], level=str(data.get("level") or ""))
    if not is_feed_url(token.url):
        raise DxlinkError("the quote token's feed address is not tastytrade's dxFeed host")
    _quote = (token, _clock() + QUOTE_TOKEN_TTL_SECONDS)
    return token


def _forget_quote_token() -> None:
    global _quote
    _quote = None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _events(data: list[Any], event_type: str, fields: Sequence[str]) -> Iterator[dict[str, Any]]:
    """The ``event_type`` events in a COMPACT ``data`` list: alternating
    event types and flat value arrays, ``len(fields)`` values per event.
    Anything else in the list is skipped."""
    pairs = data if data and isinstance(data[0], list) else [data[i : i + 2] for i in range(0, len(data), 2)]
    width = len(fields)
    for pair in pairs:
        if not isinstance(pair, list) or len(pair) != 2 or pair[0] != event_type or not isinstance(pair[1], list):
            continue
        values = pair[1]
        for start in range(0, len(values) - width + 1, width):
            row = dict(zip(fields, values[start : start + width], strict=True))
            yield {
                name: (value if isinstance(value, str) else None) if name in _TEXT_FIELDS else _number(value)
                for name, value in row.items()
            }


def _error_code(message: dict[str, Any]) -> str:
    code = message.get("error")
    return code if isinstance(code, str) and code in _ERROR_CODES else "unknown"


async def _send(ws: Any, message: dict[str, Any]) -> None:
    await ws.send(json.dumps(message))


async def _receive(ws: Any) -> dict[str, Any] | None:
    """The next message as a dict; None for one that isn't a JSON object."""
    try:
        message = json.loads(await ws.recv())
    except ValueError:
        return None
    if not isinstance(message, dict):
        return None
    if message.get("type") == "ERROR":
        raise DxlinkError(f"DXLink error: {_error_code(message)}")
    return message


async def _expect(ws: Any, kind: str) -> dict[str, Any]:
    while True:
        message = await _receive(ws)
        if message is not None and message.get("type") == kind:
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
    sent = config.get("eventFields")
    given = sent.get(event_type) if isinstance(sent, dict) else None
    if isinstance(given, list) and given and all(isinstance(name, str) for name in given):
        return given
    return wanted


# An event handler's answer: None to read on, True when the fetch is done
# and complete, False to stop short.
OnEvent = Callable[[dict[str, Any]], "bool | None"]


async def _read(ws: Any, event_type: str, fields: list[str], on_event: OnEvent, deadline: float) -> bool:
    loop = asyncio.get_running_loop()
    seen = 0
    while loop.time() < deadline:
        try:
            if seen:
                async with asyncio.timeout(IDLE_SECONDS):
                    message = await _receive(ws)
            else:
                message = await _receive(ws)
        except TimeoutError:  # quiet after events: the inner timeout's
            return False
        if message is None or message.get("type") != "FEED_DATA" or not isinstance(message.get("data"), list):
            continue
        for event in _events(message["data"], event_type, fields):
            seen += 1
            if seen > MAX_EVENTS:
                return False
            answer = on_event(event)
            if answer is not None:
                return answer
    return False


async def _run(event_type: str, subscriptions: list[dict[str, Any]], on_event: OnEvent) -> bool:
    """Opens a session, subscribes, and hands each ``event_type`` event to
    ``on_event`` until it answers. False when the feed went quiet, a cap
    was reached or the time ran out after subscribing. ``DxlinkError``
    when the session couldn't be set up in time or failed."""
    token = await quote_token()
    lock = _lock()
    try:
        async with asyncio.timeout(2 * FETCH_TIMEOUT_SECONDS):
            await lock.acquire()
    except TimeoutError:
        raise DxlinkError("another DXLink session is still open") from None
    subscribed = False
    result = False
    try:
        deadline = asyncio.get_running_loop().time() + FETCH_TIMEOUT_SECONDS
        async with asyncio.timeout_at(deadline):
            async with _connect(
                token.url,
                open_timeout=OPEN_TIMEOUT_SECONDS,
                max_size=MAX_MESSAGE_BYTES,
                max_queue=MAX_QUEUE,
                compression=None,
                logger=_WS_LOGGER,
            ) as ws:
                fields = await _open_feed(ws, token, event_type)
                await _send(ws, {"type": "FEED_SUBSCRIPTION", "channel": _CHANNEL, "reset": True, "add": subscriptions})
                subscribed = True
                result = await _read(ws, event_type, fields, on_event, deadline)
        return result
    except TimeoutError:
        if not subscribed:
            raise DxlinkError("DXLink timed out before the feed opened") from None
        return result  # a close that ran past the deadline keeps what was read
    except DxlinkError:
        raise
    except Exception as exc:  # the server's text stays out of the message
        raise DxlinkError(f"the DXLink session failed ({type(exc).__name__})") from None
    finally:
        lock.release()


def _candle(event: dict[str, Any]) -> Candle | None:
    millis = event.get("time")
    if millis is None:
        return None
    try:
        start = datetime.fromtimestamp(millis / 1000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
    return Candle(
        time=start,
        open=event.get("open"),
        high=event.get("high"),
        low=event.get("low"),
        close=event.get("close"),
        volume=event.get("volume"),
        imp_volatility=event.get("impVolatility"),
        open_interest=event.get("openInterest"),
    )


async def fetch_candles(symbol: str, period: str, from_time: datetime) -> CandleHistory:
    """``symbol``'s candles of ``period`` (dxFeed's codes: ``d``, ``h``,
    ``5m``) from ``from_time``, oldest first, at most ``MAX_CANDLES``.
    ``symbol`` is a streamer symbol (an option's comes from the chain's
    ``streamer-symbol``)."""
    candle_symbol = f"{symbol}{{={period}}}"
    echoed = f"{symbol}{{="  # the server's normal form differs in the period: SPY{=1d} -> SPY{=d}
    from_value = int(from_time.timestamp() * 1000)
    by_time: dict[datetime, Candle] = {}
    snipped = False

    def on_event(event: dict[str, Any]) -> bool | None:
        nonlocal snipped
        event_symbol = event.get("eventSymbol")
        if not isinstance(event_symbol, str) or not event_symbol.startswith(echoed):
            return None
        flags = int(event.get("eventFlags") or 0)
        candle = _candle(event)
        if candle is not None and not flags & REMOVE_EVENT:
            by_time[candle.time] = candle
        if flags & SNAPSHOT_SNIP:  # cut short: what came is all, but not the whole history
            snipped = True
            return False
        if flags & SNAPSHOT_END:
            return True
        return False if len(by_time) >= MAX_CANDLES else None

    summary = {"symbol": candle_symbol, "from": from_time.date().isoformat()}
    with log_external_call("dxlink.candles", summary) as call:
        complete = await _run("Candle", [{"type": "Candle", "symbol": candle_symbol, "fromTime": from_value}], on_event)
        call.record_output({"candles": len(by_time), "complete": complete, "snipped": snipped})
    return CandleHistory(candles=tuple(by_time[t] for t in sorted(by_time)), complete=complete, snipped=snipped)


async def fetch_once(event_type: str, symbols: Sequence[str]) -> dict[str, dict[str, Any]]:
    """The first ``event_type`` event (Summary, Greeks, Quote) for each of
    ``symbols``, by symbol; a symbol that sent none is missing."""
    wanted = set(symbols)
    found: dict[str, dict[str, Any]] = {}

    def on_event(event: dict[str, Any]) -> bool | None:
        symbol = event.get("eventSymbol")
        if isinstance(symbol, str) and symbol in wanted and symbol not in found:
            found[symbol] = event
        return True if len(found) == len(wanted) else None

    with log_external_call(f"dxlink.{event_type.lower()}", {"symbols": len(wanted)}) as call:
        await _run(event_type, [{"type": event_type, "symbol": s} for s in sorted(wanted)], on_event)
        call.record_output({"events": len(found)})
    return found
