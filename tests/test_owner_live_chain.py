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
    assert (await _get("/v1/owner/options/SPY/live/2026-12-19", owner)).status_code == 404
    assert (await _get(f"/v1/owner/options/not!a!ticker/live/{EXPIRY}", owner)).status_code == 422


async def test_the_route_is_a_503_with_the_reason(account: _Tastytrade, owner: dict[str, str]) -> None:
    account.fail = tt.TastytradeUnavailable("tastytrade answered 503")
    resp = await _get(f"/v1/owner/options/SPY/live/{EXPIRY}", owner)
    assert resp.status_code == 503 and "503" in resp.json()["title"]
