"""The owner's open positions, live from tastytrade (ADR 0009, amended
2026-11-15).

Read when the owner opens the positions page, kept CACHE_SECONDS in memory
so a refresh is free, never stored and never put in a prompt. Live marks,
IVs and Greeks are tastytrade's data; the positions themselves are the
owner's. Accounts are numbered 1, 2, ... and an account number never leaves
this module: not in the response, not in a log line (the client masks it in
paths, and logs a query's values only as counts).

Each position is kept by its instrument type: an equity option is read from
its OCC symbol, a stock is a stock leg, and anything else (a future, crypto,
a row that can't be read) is listed as not analysed. Nothing from
tastytrade's answer is trusted: a number that isn't finite is no number, a
ticker that isn't one or a position that doesn't say long or short isn't
analysed, and an answer of the wrong shape reads as nothing. Quotes come
from one REST call per QUOTE_BATCH symbols; no DXLink.
"""
from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any, Literal

from app.schemas.owner import (
    LiveQuote,
    OwnerPositions,
    PositionGroup,
    PositionLeg,
    UnanalysedPosition,
)
from app.services import tastytrade_client as tt

logger = logging.getLogger(__name__)

CACHE_SECONDS = 15.0
# How long the last copy may stand in when tastytrade fails: briefly
# (ADR 0009), not for hours after a grant is revoked.
STALE_MAX_SECONDS = 900.0
ACCOUNTS_SECONDS = 3600.0
QUOTE_BATCH = 100
# Symbols of a refused batch asked for again one at a time (a refusal is a
# quick 4xx; more than this many, and the rest go without).
RETRY_ALONE = 25
# Bounds on one build, so a huge or slow answer can't hold every owner
# request for minutes.
MAX_ACCOUNTS = 10
MAX_POSITIONS = 500
BUILD_SECONDS = 60.0
STANDARD_MULTIPLIER = 100
# A quote's IV is read as a fraction; one this large would be percent
# points. The probe checks tastytrade's units (tastytrade_probe).
IV_FRACTION_MAX = 3.0
_ACCOUNT = re.compile(r"[A-Z0-9]+")
_TICKER = re.compile(r"[A-Z][A-Z0-9.]{0,9}(?:/[A-Z0-9]{1,4})?")
# OCC: a 6-character root padded with spaces, YYMMDD, C or P, and the
# strike in thousandths over 8 digits ("SPY   261218C00600000").
_OCC = re.compile(r"(?P<root>[A-Z][A-Z0-9 ]{5})(?P<date>\d{6})(?P<kind>[CP])(?P<strike>\d{8})")
_KINDS: dict[str, Literal["call", "put"]] = {"C": "call", "P": "put"}
_SIGNS = {"Long": 1, "Short": -1}


class PositionsUnavailable(Exception):
    """tastytrade isn't set up or didn't answer, and nothing usable is cached."""


@dataclass(frozen=True)
class OccSymbol:
    root: str
    expiry: date
    kind: Literal["call", "put"]
    strike: float


def parse_occ(symbol: str) -> OccSymbol:
    """The parts of an OCC option symbol; ``ValueError`` for anything else."""
    match = _OCC.fullmatch(symbol)
    if match is None:
        raise ValueError("not an OCC option symbol")
    return OccSymbol(
        root=match["root"].rstrip(),
        expiry=datetime.strptime(match["date"], "%y%m%d").date(),
        kind=_KINDS[match["kind"]],
        strike=int(match["strike"]) / 1000,
    )


# Swapped in tests.
def _clock() -> float:
    return time.monotonic()


def _now() -> datetime:
    return datetime.now(UTC)


_cache: tuple[float, OwnerPositions] | None = None
_accounts: tuple[float, list[str]] | None = None
_lock = asyncio.Lock()


def reset() -> None:
    """Forget what's cached (tests)."""
    global _cache, _accounts, _lock
    _cache, _accounts, _lock = None, None, asyncio.Lock()


def _field(item: dict[str, Any], name: str) -> Any:
    """A field by its dashed name, or the camelCase one the spec also shows."""
    if name in item:
        return item[name]
    head, *rest = name.split("-")
    return item.get(head + "".join(part.title() for part in rest))


def _number(value: Any) -> float | None:
    """A finite number, or None: NaN and infinity can't go out as JSON."""
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _count(value: Any) -> int | None:
    """A positive whole number (a contract multiplier), or None."""
    number = _number(value)
    return int(number) if number is not None and number > 0 and number.is_integer() else None


def _items(payload: Any, *, strict: bool = False) -> list[dict[str, Any]]:
    """``data.items`` of an answer, the objects only. An answer of another
    shape is nothing, or, when ``strict`` (accounts and positions, where
    nothing would read as "no positions"), a failure."""
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        if strict:
            raise tt.TastytradeUnavailable("tastytrade's answer wasn't readable")
        return []
    return [i for i in items if isinstance(i, dict)]


async def _account_numbers() -> list[str]:
    """The owner's account numbers, read once an hour; more than MAX_ACCOUNTS
    is cut off (the caller says so). One that isn't letters and digits is
    dropped, so it never reaches a path; none at all isn't remembered."""
    global _accounts
    if _accounts is not None and _clock() - _accounts[0] < ACCOUNTS_SECONDS:
        return _accounts[1]
    payload = await tt.get("/customers/me/accounts", op="accounts")
    numbers = []
    for entry in _items(payload, strict=True):
        account = _field(entry, "account")
        number = _field(account, "account-number") if isinstance(account, dict) else None
        if isinstance(number, str) and _ACCOUNT.fullmatch(number):
            numbers.append(number)
    _accounts = (_clock(), numbers) if numbers else None
    return numbers


@dataclass
class _Leg:
    underlying: str
    leg: PositionLeg


def _text(item: dict[str, Any], name: str) -> str:
    value = _field(item, name)
    return value if isinstance(value, str) else ""


def _read(item: dict[str, Any], account: int) -> _Leg | UnanalysedPosition | None:
    """One position row as a leg, as not analysed, or None when it's closed."""
    kind = _text(item, "instrument-type")
    symbol = _text(item, "symbol")
    direction = _field(item, "quantity-direction")
    size = _number(_field(item, "quantity"))
    if direction == "Zero" or size == 0:
        return None
    sign = _SIGNS.get(direction) if isinstance(direction, str) else None
    quantity = None if size is None or sign is None else sign * size
    other = UnanalysedPosition(account=account, instrument_type=kind or "Unknown", symbol=symbol, quantity=quantity)
    # A share is one share, whatever the row says; an option needs a stated
    # multiplier (without one its deliverable is unknown, and it isn't modelled).
    multiplier = 1 if kind == "Equity" else _count(_field(item, "multiplier"))
    if quantity is None or multiplier is None or kind not in ("Equity Option", "Equity"):
        return other
    average = _number(_field(item, "average-open-price"))
    if kind == "Equity":
        if not _TICKER.fullmatch(symbol):
            return other
        return _Leg(symbol, PositionLeg(account=account, kind="stock", symbol=symbol, quantity=quantity,
                                        multiplier=multiplier, average_open=average))
    underlying = _text(item, "underlying-symbol")
    try:
        occ = parse_occ(symbol)
    except ValueError:
        return other
    if not _TICKER.fullmatch(underlying):
        return other
    adjusted = multiplier != STANDARD_MULTIPLIER or any(c.isdigit() for c in occ.root)
    return _Leg(underlying, PositionLeg(
        account=account, kind=occ.kind, symbol=symbol, expiry=occ.expiry, strike=occ.strike,
        quantity=quantity, multiplier=multiplier, average_open=average, adjusted=adjusted,
    ))


def _fraction(iv: float | None) -> float | None:
    """An IV the page can read as a fraction (0.48 = 48%), or none: a value
    of IV_FRACTION_MAX or more would be percent points (4800% on the page)."""
    return iv if iv is not None and 0 < iv < IV_FRACTION_MAX else None


def _live_quote(item: dict[str, Any]) -> LiveQuote:
    stamp = _field(item, "updated-at")
    try:
        updated = datetime.fromisoformat(stamp) if isinstance(stamp, str) else None
    except ValueError:
        updated = None
    mark = _number(_field(item, "mark"))
    return LiveQuote(
        bid=_number(_field(item, "bid")),
        ask=_number(_field(item, "ask")),
        mark=mark if mark is not None else _number(_field(item, "mid")),
        iv=_fraction(_number(_field(item, "volatility"))),
        delta=_number(_field(item, "delta")),
        gamma=_number(_field(item, "gamma")),
        theta=_number(_field(item, "theta")),
        vega=_number(_field(item, "vega")),
        updated_at=updated,
    )


# A 4xx that isn't about the request's symbols: a stale sign-in, a throttle.
_NOT_ABOUT_THE_SYMBOLS = frozenset({401, 429})


def _refused(exc: Exception) -> bool:
    """tastytrade refused the request itself (a 4xx about what was asked):
    asking for less may work. Anything else (a 401, a 429, a 5xx, no answer)
    fails the read."""
    if isinstance(exc, tt.TastytradeNotFound):
        return True
    status = exc.status if isinstance(exc, tt.TastytradeUnavailable) else None
    return status is not None and 400 <= status < 500 and status not in _NOT_ABOUT_THE_SYMBOLS


async def _quote_batch(kind: str, batch: list[str], quotes: dict[str, LiveQuote]) -> bool:
    """Ask for one batch; False when tastytrade refuses it. Any other failure
    is raised: the read fails, and the last copy stands in."""
    try:
        payload = await tt.get("/market-data/by-type", {kind: ",".join(batch)}, op="quotes")
    except (tt.TastytradeUnavailable, tt.TastytradeNotFound) as exc:
        if _refused(exc):
            return False
        raise
    for item in _items(payload):
        symbol = _field(item, "symbol")
        if isinstance(symbol, str) and symbol in batch:
            quotes[symbol] = _live_quote(item)
    return True


async def _quotes(legs: list[_Leg]) -> dict[str, LiveQuote]:
    """Live quotes for every leg and underlying, QUOTE_BATCH symbols a call,
    underlyings and options asked for apart. A refused batch is asked for
    again a symbol at a time (up to RETRY_ALONE of them), so one symbol
    tastytrade won't quote (an index such as SPX, asked for as an equity)
    costs only its own quote; legs without one show none, and the rest of
    the page stands."""
    by_kind: dict[str, list[str]] = {"equity": [], "equity-option": []}
    for item in legs:
        if item.underlying not in by_kind["equity"]:
            by_kind["equity"].append(item.underlying)
        if item.leg.kind != "stock" and item.leg.symbol not in by_kind["equity-option"]:
            by_kind["equity-option"].append(item.leg.symbol)
    quotes: dict[str, LiveQuote] = {}
    refused = 0
    for kind, symbols in by_kind.items():
        for start in range(0, len(symbols), QUOTE_BATCH):
            batch = symbols[start:start + QUOTE_BATCH]
            if await _quote_batch(kind, batch, quotes):
                continue
            alone = batch[:RETRY_ALONE] if len(batch) > 1 else []
            for symbol in alone:
                if not await _quote_batch(kind, [symbol], quotes):
                    refused += 1
            refused += len(batch) - len(alone)
    if refused:
        logger.warning("owner positions: %d quotes refused", refused)
    return quotes


def _leg_order(leg: PositionLeg) -> tuple[int, date, float, str]:
    return (0 if leg.kind == "stock" else 1, leg.expiry or date.min, leg.strike or 0.0, leg.kind)


def _groups(legs: list[_Leg], quotes: dict[str, LiveQuote]) -> list[PositionGroup]:
    by_underlying: dict[str, list[PositionLeg]] = {}
    for item in legs:
        quoted = item.underlying if item.leg.kind == "stock" else item.leg.symbol
        by_underlying.setdefault(item.underlying, []).append(item.leg.model_copy(update={"quote": quotes.get(quoted)}))
    return [
        PositionGroup(
            underlying=underlying,
            symbol=underlying.replace("/", "-"),
            quote=quotes.get(underlying),
            expiries=sorted({leg.expiry for leg in group if leg.expiry is not None}),
            legs=sorted(group, key=_leg_order),
        )
        for underlying, group in sorted(by_underlying.items())
    ]


async def _build() -> OwnerPositions:
    numbers = await _account_numbers()
    truncated = len(numbers) > MAX_ACCOUNTS
    numbers = numbers[:MAX_ACCOUNTS]
    legs: list[_Leg] = []
    unanalysed: list[UnanalysedPosition] = []
    for index, number in enumerate(numbers, start=1):
        if len(legs) + len(unanalysed) >= MAX_POSITIONS:
            truncated = True
            break  # no more accounts asked for than can be shown
        try:
            rows = _items(await tt.get(f"/accounts/{number}/positions", op="positions"), strict=True)
        except tt.TastytradeNotFound:
            continue  # that account has gone; the rest still count
        for item in rows:
            if len(legs) + len(unanalysed) >= MAX_POSITIONS:
                truncated = True
                break
            read = _read(item, index)
            if isinstance(read, _Leg):
                legs.append(read)
            elif read is not None:
                unanalysed.append(read)
    groups = _groups(legs, await _quotes(legs))
    logger.info(
        "owner positions: %d accounts, %d legs, %d underlyings, %d not analysed%s",
        len(numbers), len(legs), len(groups), len(unanalysed), ", cut off" if truncated else "",
    )
    return OwnerPositions(
        as_of=_now(), accounts=len(numbers), groups=groups, unanalysed=unanalysed, truncated=truncated
    )


async def get_positions() -> OwnerPositions:
    """The owner's positions, at most CACHE_SECONDS old; the last copy,
    marked stale, when tastytrade fails and it's under STALE_MAX_SECONDS
    old; ``PositionsUnavailable`` with the reason otherwise."""
    global _cache
    if not tt.is_configured():
        raise PositionsUnavailable("tastytrade isn't set up on the server")
    try:
        # The deadline covers waiting behind another read too.
        async with asyncio.timeout(BUILD_SECONDS), _lock:
            if _cache is not None and _clock() - _cache[0] < CACHE_SECONDS:
                return _cache[1]
            built = await _build()
            _cache = (_clock(), built)
            return built
    except (tt.TastytradeUnavailable, tt.TastytradeNotFound, TimeoutError) as exc:
        if _cache is not None and _clock() - _cache[0] < STALE_MAX_SECONDS:
            return _cache[1].model_copy(update={"stale": True})
        _cache = None
        raise PositionsUnavailable(_reason(exc)) from exc


_ACCOUNT_PATH = re.compile(r"/accounts/[^/\s]+")


def _reason(exc: Exception) -> str:
    """The 503's reason: the client's own text, any account path masked."""
    if isinstance(exc, TimeoutError):
        return "tastytrade took too long to answer"
    if isinstance(exc, tt.TastytradeUnavailable) and str(exc):
        return _ACCOUNT_PATH.sub("/accounts/***", str(exc))
    return "tastytrade didn't answer"
