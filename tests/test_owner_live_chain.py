"""One expiry's chain, live from tastytrade, for the owner (ADR 0009, PR B).

tastytrade's quotes go through the same smile, IV and positioning code as
Yahoo's chain, so the page draws them the same way. Kept 10 seconds in
memory, never stored, never in a prompt, never in the demo. tastytrade is
faked here with quotes priced by Black-76 at a flat 20% volatility, so the
smile should come back flat at 20%.
"""
from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.v1 import dependencies as deps
from app.core import settings as settings_module
from app.main import app
from app.services import market_calendar as mc
from app.services import options_math as om
from app.services import owner_live_chain as lc
from app.services import tastytrade_client as tt

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)  # Monday, in the session
EXPIRY = date(2026, 12, 18)
SPOT = 671.0
RATE = 0.04
VOL = 0.20
OWNER_KEY = "o" * 40  # plainly fake


def _occ(kind: str, strike: float) -> str:
    return f"SPY   {EXPIRY:%y%m%d}{kind}{int(strike * 1000):08d}"


STRIKES = [600.0 + 5 * i for i in range(29)]  # 600 to 740


def _quotes() -> dict[str, dict[str, Any]]:
    years = mc.years_to_expiry(NOW, EXPIRY)
    forward = SPOT * math.exp(RATE * years)
    discount = math.exp(-RATE * years)
    out: dict[str, dict[str, Any]] = {"SPY": {"symbol": "SPY", "mark": SPOT, "updated-at": "2026-11-16T14:59:59+00:00"}}
    for k in STRIKES:
        for kind, call in (("C", True), ("P", False)):
            mid = om.black76(forward, k, years, VOL, discount, call=call)
            out[_occ(kind, k)] = {
                "symbol": _occ(kind, k), "bid": round(mid - 0.02, 4), "ask": round(mid + 0.02, 4),
                "volume": 10, "open-interest": 1000 if kind == "C" else 800, "updated-at": "2026-11-16T14:59:58+00:00",
            }
    return out


class _Tastytrade:
    def __init__(self) -> None:
        self.quotes = _quotes()
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.fail: Exception | None = None

    async def get(self, path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        self.calls.append((path, params))
        if self.fail:
            raise self.fail
        if path == "/option-chains/SPY/nested":
            strikes = [{"strike-price": f"{k:.1f}", "call": _occ("C", k), "put": _occ("P", k)} for k in STRIKES]
            return {"data": {"items": [{
                "underlying-symbol": "SPY", "root-symbol": "SPY", "shares-per-contract": 100,
                "expirations": [{"expiration-date": EXPIRY.isoformat(), "strikes": strikes}],
            }]}}
        if path == "/market-data/by-type":
            asked = [s for v in (params or {}).values() for s in str(v).split(",")]
            return {"data": {"items": [self.quotes[s] for s in asked if s in self.quotes]}}
        raise AssertionError(path)

    def option_symbols_asked(self) -> int:
        return sum(len(str((p or {}).get("equity-option", "")).split(",")) for path, p in self.calls
                   if path == "/market-data/by-type" and (p or {}).get("equity-option"))


@pytest.fixture
def account(monkeypatch: pytest.MonkeyPatch) -> _Tastytrade:
    fake = _Tastytrade()
    monkeypatch.setattr(lc.tt, "get", fake.get)
    monkeypatch.setattr(lc.tt, "is_configured", lambda: True)
    monkeypatch.setattr(lc.options_chain, "risk_free_rate", lambda: (RATE, False))
    monkeypatch.setattr(lc, "_now", lambda: NOW)
    clock = [1000.0]
    monkeypatch.setattr(lc, "_clock", lambda: clock[0])
    fake.clock = clock  # type: ignore[attr-defined]
    lc.reset()
    yield fake
    lc.reset()


async def test_a_live_chain_reads_like_the_delayed_one(account: _Tastytrade) -> None:
    live = await lc.live_chain("SPY", EXPIRY)
    assert live.source == "tastytrade" and live.spot == SPOT and live.expiry == EXPIRY
    assert live.updated_at is not None
    chain = live.chain
    assert chain.expiry == EXPIRY and chain.rows and chain.smile
    assert chain.atm_iv == pytest.approx(VOL, abs=0.005)  # our own IVs from tastytrade's mids
    assert all(p.iv == pytest.approx(VOL, abs=0.01) for p in chain.smile)
    assert chain.positioning is not None and chain.positioning.call_open_interest > 0


async def test_only_the_strikes_near_the_price_are_quoted(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lc, "STRIKES_EACH_SIDE", 5)
    await lc.live_chain("SPY", EXPIRY)
    assert account.option_symbols_asked() == 2 * 10  # ten strikes, both sides


async def test_a_second_look_within_ten_seconds_asks_nothing(account: _Tastytrade) -> None:
    await lc.live_chain("SPY", EXPIRY)
    asked = len(account.calls)
    account.clock[0] += lc.CACHE_SECONDS - 1  # type: ignore[attr-defined]
    await lc.live_chain("SPY", EXPIRY)
    assert len(account.calls) == asked
    account.clock[0] += 2  # type: ignore[attr-defined]
    await lc.live_chain("SPY", EXPIRY)
    assert [p for p, _ in account.calls[asked:]].count("/option-chains/SPY/nested") == 0  # the strikes are kept longer


async def test_an_expiry_tastytrade_doesnt_list_is_said_so(account: _Tastytrade) -> None:
    with pytest.raises(lc.NotListed):
        await lc.live_chain("SPY", date(2026, 12, 19))


async def test_without_tastytrade_it_says_why(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lc.tt, "is_configured", lambda: False)
    with pytest.raises(lc.LiveChainUnavailable, match="isn't set up"):
        await lc.live_chain("SPY", EXPIRY)
    monkeypatch.setattr(lc.tt, "is_configured", lambda: True)
    account.fail = tt.TastytradeUnavailable("tastytrade answered 503")
    with pytest.raises(lc.LiveChainUnavailable, match="503"):
        await lc.live_chain("SPY", EXPIRY)


async def test_quotes_with_nothing_to_price_say_so(account: _Tastytrade) -> None:
    for item in account.quotes.values():
        if item["symbol"] != "SPY":
            item["bid"], item["ask"] = 0, 0
    with pytest.raises(lc.LiveChainUnavailable, match="no usable quotes"):
        await lc.live_chain("SPY", EXPIRY)


async def test_a_ticker_with_a_dash_is_tastytrades_slash(account: _Tastytrade) -> None:
    with pytest.raises(AssertionError, match="BRK%2FB"):  # the fake knows only SPY: the path is what matters
        await lc.live_chain("BRK-B", EXPIRY)


# ── The route ───────────────────────────────────────────────────────────


async def _get(path: str, headers: dict[str, str]) -> Any:
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers)


@pytest.fixture
def owner(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", "")
    monkeypatch.setattr(settings_module.settings, "OWNER_KEY", SecretStr(OWNER_KEY))
    deps.reset_owner_failures_for_tests()
    return {deps.OWNER_HEADER: OWNER_KEY}


async def test_the_route_serves_the_live_chain_to_the_owner_only(account: _Tastytrade, owner: dict[str, str]) -> None:
    path = f"/v1/owner/options/spy/live/{EXPIRY}"
    assert (await _get(path, {})).status_code == 403
    resp = await _get(path, owner)
    assert resp.status_code == 200 and resp.headers["Cache-Control"] == "no-store"
    assert resp.json()["chain"]["expiry"] == EXPIRY.isoformat()
    # Not a 404: the page reads a 404 from an owner route as "no owner key
    # on the server" and would forget the key (PR B's security review).
    unlisted = await _get("/v1/owner/options/SPY/live/2026-12-19", owner)
    assert unlisted.status_code == 422 and "lists no SPY options" in unlisted.json()["title"]
    for bad in ("not!a!ticker", "A-B-C", "A.", "BF.B.C", "A--B"):
        assert (await _get(f"/v1/owner/options/{bad}/live/{EXPIRY}", owner)).status_code == 422, bad


async def test_the_route_is_a_503_with_the_reason(account: _Tastytrade, owner: dict[str, str]) -> None:
    account.fail = tt.TastytradeUnavailable("tastytrade answered 503")
    resp = await _get(f"/v1/owner/options/SPY/live/{EXPIRY}", owner)
    assert resp.status_code == 503 and "503" in resp.json()["title"]


async def test_the_chains_kept_are_few_and_fresh(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    """A chain is big; only the last few, and only for CHAIN_SECONDS."""
    monkeypatch.setattr(lc, "MAX_CHAINS", 3)
    for symbol in ("A", "B", "C", "D"):
        lc._remember_chain(symbol, {})
    assert list(lc._chains) == ["B", "C", "D"]
    account.clock[0] += lc.CHAIN_SECONDS + 1  # type: ignore[attr-defined]
    lc._remember_chain("E", {})
    assert list(lc._chains) == ["E"]


async def test_a_build_that_runs_too_long_says_so(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    import asyncio

    async def slow(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        await asyncio.sleep(1)
        return {}

    monkeypatch.setattr(lc.tt, "get", slow)
    monkeypatch.setattr(lc, "BUILD_SECONDS", 0.01)
    with pytest.raises(lc.LiveChainUnavailable, match="too long"):
        await lc.live_chain("SPY", EXPIRY)


async def test_overlapping_reads_of_one_expiry_build_it_once(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    """A read waiting on a build that fails, and another arriving as it's
    woken, build one after the other, not side by side (#130's AI review:
    the lock was dropped while one still waited on it)."""
    import asyncio

    slow = account.get
    failures = [tt.TastytradeUnavailable("tastytrade answered 503")]

    async def get(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        await asyncio.sleep(0.01)
        if failures:
            raise failures.pop()
        return await slow(path, params, op=op)

    monkeypatch.setattr(lc.tt, "get", get)
    first = asyncio.ensure_future(lc.live_chain("SPY", EXPIRY))
    await asyncio.sleep(0)
    second = asyncio.ensure_future(lc.live_chain("SPY", EXPIRY))
    await asyncio.sleep(0)
    with pytest.raises(lc.LiveChainUnavailable):
        await first  # fails, waking the second; a third arrives in that moment
    third = asyncio.ensure_future(lc.live_chain("SPY", EXPIRY))
    await asyncio.gather(second, third)
    assert sum(1 for path, _ in account.calls if path == "/option-chains/SPY/nested") == 1  # the second built; the third read its copy
    assert lc._locks == {}  # nothing left behind


async def test_no_live_price_for_the_underlying_is_said_so(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    """The delayed price isn't passed off as live, even with one cached
    (#130's AI review)."""
    monkeypatch.setattr(lc.options_report, "cached_underlying", lambda _s: (SPOT * 0.98, 0.012))
    del account.quotes["SPY"]
    with pytest.raises(lc.LiveChainUnavailable, match="no price for the underlying"):
        await lc.live_chain("SPY", EXPIRY)


async def test_one_strike_is_quoted_once_whatever_roots_list_it(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    """An adjusted root that still declares 100 shares (or SPX beside SPXW)
    lists the same strikes again: each strike is kept once, the standard
    root's, so its open interest isn't doubled (#130's AI review)."""
    plain = account.get

    async def get(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        answer = await plain(path, params, op=op)
        if path == "/option-chains/SPY/nested":
            twin = {**answer["data"]["items"][0], "root-symbol": "SPY1"}
            twin["expirations"] = [{
                "expiration-date": EXPIRY.isoformat(),
                "strikes": [{"strike-price": f"{k:.1f}", "call": _occ("C", k).replace("SPY   ", "SPY1  "),
                             "put": _occ("P", k).replace("SPY   ", "SPY1  ")} for k in STRIKES],
            }]
            answer = {"data": {"items": [twin, *answer["data"]["items"]]}}
        return answer

    monkeypatch.setattr(lc.tt, "get", get)
    chain = (await lc.live_chain("SPY", EXPIRY)).chain
    strikes = [row.strike for row in chain.rows]
    assert len(strikes) == len(set(strikes))
    asked = [s for path, p in account.calls if path == "/market-data/by-type" for s in str((p or {}).get("equity-option", "")).split(",") if s]
    assert asked and all(s.startswith("SPY   ") for s in asked)  # the standard root's contracts


async def test_a_chain_is_kept_as_plain_rows(account: _Tastytrade) -> None:
    """A big chain (SPY, SPX) is every expiry's strikes: kept as (strike,
    call, put) rows by expiry, not tastytrade's dicts, so ten of them stay
    small on a 512 MB machine (#130's AI review)."""
    await lc.live_chain("SPY", EXPIRY)
    _at, kept = lc._chains["SPY"]
    assert set(kept) == {EXPIRY.isoformat()}
    rows = kept[EXPIRY.isoformat()]
    assert len(rows) == len(STRIKES) and all(isinstance(r, tuple) and len(r) == 3 for r in rows)


async def test_a_chain_is_read_into_rows_off_the_event_loop(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    """SPY's or SPX's nested chain is tens of thousands of strikes: turned
    into rows on the options thread, not the event loop (#130's AI review)."""
    import threading

    rows = lc._rows
    threads: list[bool] = []

    def recording(expiration: dict[str, Any]) -> list[tuple[float, str, str]]:
        threads.append(threading.current_thread() is threading.main_thread())
        return rows(expiration)

    monkeypatch.setattr(lc, "_rows", recording)
    await lc.live_chain("SPY", EXPIRY)
    assert threads and not any(threads)


async def test_an_expiry_listed_since_the_chain_was_kept_is_found(account: _Tastytrade) -> None:
    """The kept chain is read again before saying an expiry isn't listed: a
    weekly listed since then would otherwise be "not listed" for ten minutes
    (#130's AI review)."""
    later = date(2026, 12, 24)
    await lc.live_chain("SPY", EXPIRY)  # keeps the chain
    account.clock[0] += lc.CHAIN_RECHECK_SECONDS  # type: ignore[attr-defined]
    with pytest.raises(lc.NotListed):
        await lc.live_chain("SPY", later)
    assert sum(1 for path, _ in account.calls if path == "/option-chains/SPY/nested") == 2  # read again once


async def test_an_expiry_that_has_closed_is_not_priced(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    """After its close an expiry has no time left: not priced at a negative one."""
    monkeypatch.setattr(lc, "_now", lambda: datetime(2026, 12, 18, 22, tzinfo=UTC))  # after EXPIRY's close
    with pytest.raises(lc.NotListed):
        await lc.live_chain("SPY", EXPIRY)


async def test_a_contract_filed_under_another_strike_is_dropped(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    """A strike row whose contract says another strike would shift the smile:
    dropped (#130's AI review)."""
    plain = account.get

    async def get(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        answer = await plain(path, params, op=op)
        if path == "/option-chains/SPY/nested":
            strikes = answer["data"]["items"][0]["expirations"][0]["strikes"]
            strikes[0] = {**strikes[0], "strike-price": f"{STRIKES[0] + 1:.1f}"}  # files the first contract a dollar off
        return answer

    monkeypatch.setattr(lc.tt, "get", get)
    chain = (await lc.live_chain("SPY", EXPIRY)).chain
    assert STRIKES[0] + 1 not in [row.strike for row in chain.rows]


async def test_a_symbol_tastytrade_lists_no_options_for_is_not_listed(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    """Not a provider outage: no options for it (#130's AI review)."""
    async def get(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        raise tt.TastytradeNotFound(path)

    monkeypatch.setattr(lc.tt, "get", get)
    with pytest.raises(lc.NotListed):
        await lc.live_chain("SPY", EXPIRY)


async def test_an_unlisted_expiry_reads_the_chain_again_at_most_once_a_minute(account: _Tastytrade) -> None:
    """Live polls every 15 s: an expiry tastytrade doesn't list mustn't
    re-read the whole chain each time (#130's AI review)."""
    later = date(2026, 12, 24)
    await lc.live_chain("SPY", EXPIRY)
    for _ in range(3):
        with pytest.raises(lc.NotListed):
            await lc.live_chain("SPY", later)
        account.clock[0] += 15  # type: ignore[attr-defined]
    reads = sum(1 for path, _ in account.calls if path == "/option-chains/SPY/nested")
    assert reads == 1  # the kept chain answers inside the minute
    account.clock[0] += lc.CHAIN_RECHECK_SECONDS  # type: ignore[attr-defined]
    with pytest.raises(lc.NotListed):
        await lc.live_chain("SPY", later)
    assert sum(1 for path, _ in account.calls if path == "/option-chains/SPY/nested") == 2  # one fresh look


async def test_a_strike_without_a_quote_isnt_drawn_at_zero(account: _Tastytrade) -> None:
    """A contract tastytrade sends no quote for isn't a $0.00 row (#130's AI review)."""
    for kind in ("C", "P"):
        del account.quotes[_occ(kind, STRIKES[-1])]
    chain = (await lc.live_chain("SPY", EXPIRY)).chain
    assert STRIKES[-1] not in [row.strike for row in chain.rows]


async def test_an_expiry_date_sent_with_a_time_still_reads(account: _Tastytrade, monkeypatch: pytest.MonkeyPatch) -> None:
    plain = account.get

    async def get(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        answer = await plain(path, params, op=op)
        if path == "/option-chains/SPY/nested":
            answer["data"]["items"][0]["expirations"][0]["expiration-date"] = f"{EXPIRY.isoformat()}T20:00:00.000+00:00"
        return answer

    monkeypatch.setattr(lc.tt, "get", get)
    assert (await lc.live_chain("SPY", EXPIRY)).expiry == EXPIRY


def test_few_chains_are_kept() -> None:
    """An SPX-sized chain keeps about 5.7 MB (measured with tracemalloc): four at most."""
    assert lc.MAX_CHAINS == 4

