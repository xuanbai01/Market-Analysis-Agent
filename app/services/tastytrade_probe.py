"""
What the owner's tastytrade account gets through the API (ADR 0009, PR A).

Run it where the secrets are, on the Fly machine::

    fly ssh console -C "python -m app.services.tastytrade_probe"

It prints a report and stores nothing. The questions the docs leave open:
is the feed real-time (the quote token's level, the quotes' age), how far
back candles go, whether they carry IV, whether option contracts have
candles. It also prints the wire format's field names, which the docs
show two ways.

**It prints no tastytrade value.** tastytrade's terms (§8(4), §8(6)) bar
showing its data to any third party, and whoever reads this output (a
Claude Code session included) may be one. So the report holds metadata
only: ages, counts, date ranges, field names, and yes/no answers computed
here (is tastytrade's mid inside Yahoo's spread, is its IV30 within two
points of ours). For the owner's own account it prints counts and a
month: no account number, balance or amount. An error prints its text
only when this code wrote it (``_OWN_ERRORS``); any other prints its type,
since a library's message can quote the server or a connection string.

Call logging (``log_external_call``'s INFO records) is left off on
purpose: the report is the output. Warnings, which carry no secret, still
reach stderr. Never lower the root logger here: httpx logs each request's
URL at INFO, account number and all.

Never imported by the app.
"""
from __future__ import annotations

import asyncio
import re
import statistics
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit

from app.services import dxlink
from app.services import market_calendar as mc
from app.services import tastytrade_client as tt

Say = Callable[[str], None]


class ProbeError(Exception):
    """An answer the probe can't read; its message is the probe's own."""


_OWN_ERRORS = (ProbeError, tt.TastytradeUnavailable, tt.TastytradeNotFound, dxlink.DxlinkError)
_ACCOUNT_NUMBER = re.compile(r"[A-Z0-9]+")

METRICS_SYMBOLS = ("QQQ", "SPY", "NVDA")
CHAIN_SYMBOL = "SPY"
EARNINGS_SYMBOL = "NVDA"
TARGET_DAYS = 30
NEAR_MONEY_STRIKES = 5
DAILY_FROM = datetime(2005, 1, 1, tzinfo=UTC)
# Our IV30 and tastytrade's agree when this close, in vol points.
IV30_POINTS = 2.0
METRIC_FIELDS = (
    "implied-volatility-index",
    "implied-volatility-30-day",
    "implied-volatility-index-rank",
    "tw-implied-volatility-index-rank",
    "implied-volatility-percentile",
    "historical-volatility-30-day",
    "option-expiration-implied-volatilities",
    "liquidity-rating",
    "earnings",
)


def field(item: dict[str, Any], name: str) -> Any:
    """A field by its dashed name, or the camelCase one the spec also shows."""
    if name in item:
        return item[name]
    head, *rest = name.split("-")
    return item.get(head + "".join(part.title() for part in rest))


def number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def field_names(value: Any) -> list[str] | str:
    """An object's field names; for anything else, only its type."""
    return sorted(str(k) for k in value) if isinstance(value, dict) else f"<{type(value).__name__}>"


def present(item: dict[str, Any], names: tuple[str, ...]) -> list[str]:
    """Which of ``names`` the item fills in (the names, never the values)."""
    return [name for name in names if field(item, name) not in (None, "", [], {})]


def age_seconds(stamp: Any, now: datetime) -> float | None:
    if not isinstance(stamp, str) or not stamp:
        return None
    try:
        then = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now - then).total_seconds()


def nearest_expiry(expirations: list[dict[str, Any]], today: date, target_days: int = TARGET_DAYS) -> dict[str, Any] | None:
    dated = [e for e in expirations if isinstance(field(e, "expiration-date"), str)]
    return min(
        dated,
        key=lambda e: abs((date.fromisoformat(field(e, "expiration-date")) - today).days - target_days),
        default=None,
    )


def near_money(strikes: list[dict[str, Any]], spot: float, n: int = NEAR_MONEY_STRIKES) -> list[dict[str, Any]]:
    priced = [s for s in strikes if number(field(s, "strike-price")) is not None]
    return sorted(priced, key=lambda s: abs(number(field(s, "strike-price")) - spot))[:n]


def describe_candles(history: dxlink.CandleHistory) -> str:
    candles = history.candles
    if not candles:
        return f"none (complete={history.complete})"
    with_iv = sum(1 for c in candles if c.imp_volatility is not None)
    with_oi = sum(1 for c in candles if c.open_interest is not None)
    return (
        f"{len(candles)} candles, {candles[0].time.date()} to {candles[-1].time.date()}, "
        f"complete={history.complete}, with IV {with_iv}/{len(candles)}, with open interest {with_oi}/{len(candles)}"
    )


def spread_check(mid: float | None, bid: float | None, ask: float | None) -> bool | None:
    """Whether ``mid`` lies inside the bid–ask; None when a side is missing."""
    if mid is None or bid is None or ask is None or ask <= 0:
        return None
    return bid <= mid <= ask


def iv30_agrees(ours: float | None, theirs_percent: float | None) -> bool | None:
    """Ours is a fraction (0.314); tastytrade's 30-day IV is a percentage (31.4)."""
    if ours is None or theirs_percent is None:
        return None
    return abs(ours * 100 - theirs_percent) <= IV30_POINTS


def _answer(value: bool | None) -> str:
    return {True: "yes", False: "no", None: "can't tell"}[value]


@dataclass
class ChainPick:
    spot: float
    expiry: str
    strikes: list[dict[str, Any]]  # near the money, each with call/put and their streamer symbols


async def _section(say: Say, title: str, body: Callable[[], Awaitable[Any]]) -> Any:
    say(f"\n== {title} ==")
    try:
        return await body()
    except _OWN_ERRORS as exc:
        say(f"  failed: {type(exc).__name__}: {exc}")
    except Exception as exc:  # a probe reports every failure and carries on
        say(f"  failed: {type(exc).__name__}")
    return None


async def probe_quote_token(say: Say) -> None:
    token = await dxlink.quote_token()
    parts = urlsplit(token.url)
    delayed = "/delayed" in parts.path
    say(f"  level: {token.level or '(none)'}; feed: {parts.hostname}{parts.path}; delayed URL: {'yes' if delayed else 'no'}")


async def probe_grant(say: Say) -> None:
    scopes = await tt.grant_scopes()
    say(f"  the stored grant may: {sorted(scopes) or '(not said)'}")
    if "trade" in scopes:
        say("  WARNING: the grant can trade. Delete it on my.tastytrade.com and create one with the read scope only.")


async def _spot(symbol: str) -> float:
    payload = await tt.get("/market-data/by-type", {"equity": symbol}, op="quotes")
    item = ((payload.get("data") or {}).get("items") or [{}])[0]
    for name in ("mark", "mid", "last"):
        value = number(field(item, name))
        if value:
            return value
    raise ProbeError(f"no price for {symbol}")


async def probe_chain(say: Say, today: date) -> ChainPick:
    spot = await _spot(CHAIN_SYMBOL)
    payload = await tt.get(f"/option-chains/{tt.symbol_path(CHAIN_SYMBOL)}/nested", op="option_chain")
    chains = (payload.get("data") or {}).get("items") or []
    if not chains or not isinstance(chains[0], dict):
        raise ProbeError("no chain")
    chain = chains[0]
    expirations = field(chain, "expirations") or []
    pick = nearest_expiry(expirations, today)
    if pick is None:
        raise ProbeError("no expirations")
    strikes = field(pick, "strikes") or []
    if not isinstance(strikes, list) or not all(isinstance(s, dict) for s in strikes):
        raise ProbeError("the strikes are not objects")
    say(f"  {len(chains)} chain(s), {len(expirations)} expirations; the one nearest {TARGET_DAYS} days has {len(strikes)} strikes")
    say(f"  chain fields: {field_names(chain)}")
    say(f"  expiration fields: {field_names(pick)}")
    say(f"  strike fields: {field_names(strikes[0]) if strikes else []}")
    return ChainPick(spot=spot, expiry=field(pick, "expiration-date"), strikes=near_money(strikes, spot))


def _yahoo_quotes(symbol: str, expiry: str) -> dict[tuple[str, float], tuple[float, float]]:
    import yfinance  # noqa: PLC0415

    chain = yfinance.Ticker(symbol).option_chain(expiry)
    quotes = {}
    for side, frame in (("call", chain.calls), ("put", chain.puts)):
        for strike, bid, ask in frame[["strike", "bid", "ask"]].to_numpy().tolist():
            quotes[(side, float(strike))] = (float(bid), float(ask))
    return quotes


async def probe_quotes(say: Say, pick: ChainPick, now: datetime) -> None:
    legs = [(s, side) for s in pick.strikes for side in ("call", "put") if field(s, side)]
    payload = await tt.get(
        "/market-data/by-type",
        {"equity": CHAIN_SYMBOL, "equity-option": ",".join(field(s, side) for s, side in legs)},
        op="quotes",
    )
    items = (payload.get("data") or {}).get("items") or []
    by_symbol = {field(i, "symbol"): i for i in items}
    if items:
        say(f"  quote fields: {field_names(items[0])}")
    underlying = by_symbol.get(CHAIN_SYMBOL) or {}
    underlying_age = age_seconds(field(underlying, "updated-at"), now)
    try:
        yahoo = await asyncio.to_thread(_yahoo_quotes, CHAIN_SYMBOL, pick.expiry)
    except Exception as exc:
        say(f"  Yahoo's chain unreadable: {type(exc).__name__}")
        yahoo = {}
    ages, inside = [], []
    for strike, side in legs:
        item = by_symbol.get(field(strike, side)) or {}
        age = age_seconds(field(item, "updated-at"), now)
        if age is not None:
            ages.append(age)
        yahoo_bid, yahoo_ask = yahoo.get((side, number(field(strike, "strike-price"))), (None, None))
        inside.append(spread_check(number(field(item, "mid")), yahoo_bid, yahoo_ask))
    say(f"  {len(items)} of {len(legs) + 1} quotes came back; market open now: {'yes' if mc.market_open(now) else 'no'}")
    say(f"  {CHAIN_SYMBOL} quote age: {None if underlying_age is None else round(underlying_age, 1)} s")
    if ages:
        say(f"  option quote ages: min {min(ages):.1f} s, median {statistics.median(ages):.1f} s, max {max(ages):.1f} s")
    known = [x for x in inside if x is not None]
    say(f"  tastytrade's mid inside Yahoo's (15-minute-old) bid–ask: {sum(known)} of {len(known)}")


async def _our_iv30(symbol: str) -> float | None:
    from app.db.session import SessionLocal  # noqa: PLC0415
    from app.services import options_metrics as om  # noqa: PLC0415
    from app.services import options_snapshot_store as store  # noqa: PLC0415

    async with SessionLocal() as session:
        history = await store.iv30_history(session, symbol, om.METHOD_VERSION)
    return history[-1][1] if history else None


async def probe_metrics(say: Say) -> None:
    payload = await tt.get("/market-metrics", {"symbols": ",".join(METRICS_SYMBOLS)}, op="market_metrics")
    items = (payload.get("data") or {}).get("items") or []
    for item in items:
        symbol = field(item, "symbol")
        earnings = field(item, "earnings") or {}
        try:
            ours = await _our_iv30(symbol)
        except Exception as exc:
            say(f"  {symbol}: our snapshot unreadable ({type(exc).__name__})")
            ours = None
        agrees = iv30_agrees(ours, number(field(item, "implied-volatility-30-day")))
        say(f"  {symbol}: fields filled: {present(item, METRIC_FIELDS)}")
        say(f"    earnings fields filled: {present(earnings, ('expected-report-date', 'time-of-day', 'estimated'))}")
        say(f"    IV30 within {IV30_POINTS:g} points of our latest snapshot: {_answer(agrees)}")


async def probe_candles(say: Say, pick: ChainPick | None, now: datetime) -> None:
    daily = await dxlink.fetch_candles("SPY", "1d", DAILY_FROM)
    say(f"  SPY daily from {DAILY_FROM.date()}, fromTime in seconds: {describe_candles(daily)}")
    if daily.candles and daily.candles[0].time < DAILY_FROM - timedelta(days=31):
        say("  the first candle is older than asked: DXLink may read fromTime as milliseconds")
    daily_ms = await dxlink.fetch_candles("SPY", "1d", DAILY_FROM, time_unit_ms=True)
    say(f"  SPY daily from {DAILY_FROM.date()}, fromTime in milliseconds: {describe_candles(daily_ms)}")
    hourly = await dxlink.fetch_candles("SPY", "1h", now - timedelta(days=730))
    say(f"  SPY hourly, two years asked: {describe_candles(hourly)}")
    if pick is not None and pick.strikes:
        streamer = field(pick.strikes[0], "call-streamer-symbol")
        option = await dxlink.fetch_candles(streamer, "1d", now - timedelta(days=180))
        say(f"  a near-money SPY call, daily, 180 days asked: {describe_candles(option)}")


async def probe_option_events(say: Say, pick: ChainPick) -> None:
    streamer = field(pick.strikes[0], "call-streamer-symbol")
    for event_type in ("Summary", "Greeks"):
        events = await dxlink.fetch_once(event_type, [streamer])
        event = events.get(streamer)
        filled = sorted(k for k, v in (event or {}).items() if v is not None and k not in ("eventType", "eventSymbol"))
        say(f"  {event_type} for a near-money call: {'none' if event is None else f'fields filled: {filled}'}")


async def probe_earnings(say: Say) -> None:
    payload = await tt.get(
        f"/market-metrics/historic-corporate-events/earnings-reports/{tt.symbol_path(EARNINGS_SYMBOL)}",
        {"start-date": "2015-01-01"},
        op="earnings_reports",
    )
    items = (payload.get("data") or {}).get("items") or []
    years = sorted(str(field(i, "occurred-date"))[:4] for i in items if field(i, "occurred-date"))
    say(f"  {EARNINGS_SYMBOL}: {len(items)} reports since 2015" + (f", {years[0]} to {years[-1]}" if years else ""))


def _month(item: dict[str, Any]) -> str | None:
    for name in ("executed-at", "transaction-date"):
        value = field(item, name)
        if isinstance(value, str) and len(value) >= 7:
            return value[:7]
    return None


async def probe_account(say: Say) -> None:
    """Counts and a month only: no account number, balance or amount."""
    payload = await tt.get("/customers/me/accounts", op="accounts")
    accounts = (payload.get("data") or {}).get("items") or []
    say(f"  {len(accounts)} account(s)")
    for index, entry in enumerate(accounts, start=1):
        account_number = field(field(entry, "account") or {}, "account-number")
        if not isinstance(account_number, str) or not _ACCOUNT_NUMBER.fullmatch(account_number):
            say(f"  account {index}: no account number in the expected form")
            continue
        first = await tt.get(
            f"/accounts/{account_number}/transactions", {"per-page": 1, "sort": "Asc"}, op="transactions"
        )
        total = field(first.get("pagination") or {}, "total-items")
        items = (first.get("data") or {}).get("items") or []
        since = _month(items[0]) if items else None
        positions = await tt.get(f"/accounts/{account_number}/positions", op="positions")
        held = len((positions.get("data") or {}).get("items") or [])
        say(f"  account {index}: {total} transactions, the first in {since}; {held} open positions")


async def main(say: Say = print) -> None:
    now = datetime.now(UTC)
    say(f"tastytrade probe, {now.astimezone(mc.ET):%Y-%m-%d %H:%M} ET; configured: {tt.is_configured()}")
    await _section(say, "The grant", lambda: probe_grant(say))
    await _section(say, "Quote token", lambda: probe_quote_token(say))
    pick = await _section(say, f"{CHAIN_SYMBOL} chain", lambda: probe_chain(say, now.astimezone(mc.ET).date()))
    if pick is not None:
        await _section(say, "REST quotes", lambda: probe_quotes(say, pick, now))
    await _section(say, "Market metrics", lambda: probe_metrics(say))
    await _section(say, "Candles (DXLink)", lambda: probe_candles(say, pick, now))
    if pick is not None:
        await _section(say, "Open interest and Greeks (DXLink)", lambda: probe_option_events(say, pick))
    await _section(say, "Past earnings", lambda: probe_earnings(say))
    await _section(say, "Your account (counts only)", lambda: probe_account(say))


if __name__ == "__main__":
    asyncio.run(main())
