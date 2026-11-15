"""The owner's open positions, live from tastytrade (ADR 0009, amended
2026-11-15).

Read when the owner opens the positions page, kept CACHE_SECONDS in memory
so a refresh is free, never stored and never put in a prompt. Live marks,
IVs and Greeks are tastytrade's data; the positions themselves are the
owner's. Accounts are numbered 1, 2, ... and an account number never leaves
this module: not in the response, not in a log line (the client masks it in
paths).

Each position is kept by its instrument type: an equity option is read from
its OCC symbol, a stock is a stock leg, and anything else (a future, crypto,
a row that can't be read) is listed as not analysed. Quotes come from one
REST call per QUOTE_BATCH symbols; no DXLink.
"""
from __future__ import annotations

import asyncio
import logging
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
ACCOUNTS_SECONDS = 3600.0
QUOTE_BATCH = 100
STANDARD_MULTIPLIER = 100
_ACCOUNT = re.compile(r"[A-Z0-9]+")
# OCC: a 6-character root padded with spaces, YYMMDD, C or P, and the
# strike in thousandths over 8 digits ("SPY   261218C00600000").
_OCC = re.compile(r"(?P<root>[A-Z][A-Z0-9 ]{5})(?P<date>\d{6})(?P<kind>[CP])(?P<strike>\d{8})")
_KINDS: dict[str, Literal["call", "put"]] = {"C": "call", "P": "put"}


class PositionsUnavailable(Exception):
    """tastytrade isn't set up or didn't answer, and nothing is cached."""


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
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = (payload.get("data") or {}).get("items") or []
    return [i for i in items if isinstance(i, dict)]


async def _account_numbers() -> list[str]:
    """The owner's account numbers, read once an hour. One that isn't
    letters and digits is dropped, so it never reaches a path."""
    global _accounts
    if _accounts is not None and _clock() - _accounts[0] < ACCOUNTS_SECONDS:
        return _accounts[1]
    payload = await tt.get("/customers/me/accounts", op="accounts")
    numbers = []
    for entry in _items(payload):
        number = _field(_field(entry, "account") or {}, "account-number")
        if isinstance(number, str) and _ACCOUNT.fullmatch(number):
            numbers.append(number)
    _accounts = (_clock(), numbers)
    return numbers


@dataclass
class _Leg:
    underlying: str
    leg: PositionLeg


def _read(item: dict[str, Any], account: int, legs: list[_Leg], unanalysed: list[UnanalysedPosition]) -> None:
    """Sort one position row into ``legs`` or ``unanalysed``; a closed one is left out."""
    kind = str(_field(item, "instrument-type") or "")
    symbol = str(_field(item, "symbol") or "")
    direction = _field(item, "quantity-direction")
    size = _number(_field(item, "quantity"))
    if direction == "Zero" or size == 0:
        return
    sign = -1 if direction == "Short" else 1
    multiplier = int(_number(_field(item, "multiplier")) or (STANDARD_MULTIPLIER if kind == "Equity Option" else 1))
    average = _number(_field(item, "average-open-price"))
    underlying = str(_field(item, "underlying-symbol") or symbol)
    other = UnanalysedPosition(account=account, instrument_type=kind or "Unknown", symbol=symbol,
                               quantity=None if size is None else sign * size)
    if size is None or kind not in ("Equity Option", "Equity"):
        unanalysed.append(other)
        return
    if kind == "Equity":
        legs.append(_Leg(symbol, PositionLeg(account=account, kind="stock", symbol=symbol, quantity=sign * size,
                                             multiplier=multiplier, average_open=average)))
        return
    try:
        occ = parse_occ(symbol)
    except ValueError:
        unanalysed.append(other)
        return
    adjusted = multiplier != STANDARD_MULTIPLIER or any(c.isdigit() for c in occ.root)
    legs.append(_Leg(underlying, PositionLeg(
        account=account, kind=occ.kind, symbol=symbol, expiry=occ.expiry, strike=occ.strike,
        quantity=sign * size, multiplier=multiplier, average_open=average, adjusted=adjusted,
    )))


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
        iv=_number(_field(item, "volatility")),
        delta=_number(_field(item, "delta")),
        gamma=_number(_field(item, "gamma")),
        theta=_number(_field(item, "theta")),
        vega=_number(_field(item, "vega")),
        updated_at=updated,
    )


async def _quotes(legs: list[_Leg]) -> dict[str, LiveQuote]:
    """Live quotes for every leg and underlying, QUOTE_BATCH symbols a call."""
    wanted: dict[str, str] = {}
    for item in legs:
        wanted.setdefault(item.underlying, "equity")
        if item.leg.kind != "stock":
            wanted.setdefault(item.leg.symbol, "equity-option")
    pairs = list(wanted.items())
    quotes: dict[str, LiveQuote] = {}
    for start in range(0, len(pairs), QUOTE_BATCH):
        params: dict[str, str] = {}
        for symbol, kind in pairs[start:start + QUOTE_BATCH]:
            params[kind] = f"{params[kind]},{symbol}" if kind in params else symbol
        for item in _items(await tt.get("/market-data/by-type", params, op="quotes")):
            symbol = _field(item, "symbol")
            if isinstance(symbol, str) and symbol in wanted:
                quotes[symbol] = _live_quote(item)
    return quotes


def _leg_order(leg: PositionLeg) -> tuple[int, date, float, str]:
    return (0 if leg.kind == "stock" else 1, leg.expiry or date.min, leg.strike or 0.0, leg.kind)


def _groups(legs: list[_Leg], quotes: dict[str, LiveQuote]) -> list[PositionGroup]:
    by_underlying: dict[str, list[PositionLeg]] = {}
    for item in legs:
        by_underlying.setdefault(item.underlying, []).append(
            item.leg.model_copy(update={"quote": quotes.get(item.leg.symbol)}) if item.leg.kind != "stock"
            else item.leg.model_copy(update={"quote": quotes.get(item.underlying)})
        )
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
    legs: list[_Leg] = []
    unanalysed: list[UnanalysedPosition] = []
    for index, number in enumerate(numbers, start=1):
        for item in _items(await tt.get(f"/accounts/{number}/positions", op="positions")):
            _read(item, index, legs, unanalysed)
    groups = _groups(legs, await _quotes(legs))
    logger.info(
        "owner positions: %d accounts, %d legs, %d underlyings, %d not analysed",
        len(numbers), len(legs), len(groups), len(unanalysed),
    )
    return OwnerPositions(as_of=_now(), accounts=len(numbers), groups=groups, unanalysed=unanalysed)


async def get_positions() -> OwnerPositions:
    """The owner's positions, at most CACHE_SECONDS old; the last copy,
    marked stale, when tastytrade fails; ``PositionsUnavailable`` with the
    reason when there's none."""
    global _cache
    if not tt.is_configured():
        raise PositionsUnavailable("tastytrade isn't set up on the server")
    async with _lock:
        if _cache is not None and _clock() - _cache[0] < CACHE_SECONDS:
            return _cache[1]
        try:
            built = await _build()
        except (tt.TastytradeUnavailable, tt.TastytradeNotFound) as exc:
            if _cache is not None:
                return _cache[1].model_copy(update={"stale": True})
            raise PositionsUnavailable(str(exc) or "tastytrade didn't answer") from exc
        _cache = (_clock(), built)
        return built
