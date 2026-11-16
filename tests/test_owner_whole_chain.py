"""Every expiry, live (options PR 5, ADR 0009): the owner's whole chain from
tastytrade over DXLink, each expiry read through our own smile code, the
positioning added up across them. tastytrade's chain and price and DXLink's
Quote and Summary events are faked, priced by Black-76 at a flat 20%, so
every expiry's at-the-money IV should come back at 20%.
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
from app.services import dxlink
from app.services import market_calendar as mc
from app.services import options_math as om
from app.services import owner_live_chain as lc
from app.services import owner_whole_chain as wc
from app.services import tastytrade_client as tt

NOW = datetime(2026, 11, 16, 15, 0, tzinfo=UTC)  # Monday, in the session
SPOT = 100.0
RATE = 0.04
VOL = 0.20
OWNER_KEY = "o" * 40  # plainly fake
EXPIRIES = [date(2026, 11, 20), date(2026, 12, 18), date(2027, 1, 15), date(2027, 6, 18)]  # the last past 120 days
STRIKES = [70.0 + 2.5 * i for i in range(25)]  # 70 to 130


def _occ(expiry: date, kind: str, k: float) -> str:
    return f"XYZ   {expiry:%y%m%d}{kind}{int(k * 1000):08d}"


def _streamer(expiry: date, kind: str, k: float) -> str:
    return f".XYZ{expiry:%y%m%d}{kind}{k:g}"


def _events(expiry: date, oi_call: int = 1000, oi_put: int = 800) -> tuple[dict[str, Any], dict[str, Any]]:
    years = mc.years_to_expiry(NOW, expiry)
    forward, discount = SPOT * math.exp(RATE * years), math.exp(-RATE * years)
    quotes, summaries = {}, {}
    for k in STRIKES:
        for kind, call in (("C", True), ("P", False)):
            mid = om.black76(forward, k, years, VOL, discount, call=call)
            name = _streamer(expiry, kind, k)
            quotes[name] = {"eventSymbol": name, "bidPrice": round(max(mid - 0.02, 0), 4), "askPrice": round(mid + 0.02, 4),
                            "bidTime": 1763305198000, "askTime": 1763305199000}
            summaries[name] = {"eventSymbol": name, "openInterest": oi_call if call else oi_put}
    return quotes, summaries


class _Account:
    def __init__(self) -> None:
        self.quotes: dict[str, Any] = {}
        self.summaries: dict[str, Any] = {}
        for expiry in EXPIRIES:
            q, s = _events(expiry)
            self.quotes.update(q)
            self.summaries.update(s)
        self.asked: list[tuple[str, int]] = []
        self.calls: list[str] = []
        self.fail: Exception | None = None
        self.feed_fail: Exception | None = None

    async def get(self, path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        self.calls.append(path)
        if self.fail:
            raise self.fail
        if path == "/option-chains/XYZ/nested":
            expirations = [{"expiration-date": e.isoformat(), "strikes": [
                {"strike-price": f"{k:.1f}", "call": _occ(e, "C", k), "put": _occ(e, "P", k),
                 "call-streamer-symbol": _streamer(e, "C", k), "put-streamer-symbol": _streamer(e, "P", k)}
                for k in STRIKES]} for e in EXPIRIES]
            return {"data": {"items": [{"root-symbol": "XYZ", "shares-per-contract": 100, "expirations": expirations}]}}
        if path == "/market-data/by-type":
            return {"data": {"items": [{"symbol": "XYZ", "mark": SPOT}]}}
        raise tt.TastytradeNotFound(path)

    async def fetch_once(self, event_type: str, symbols: list[str]) -> dict[str, dict[str, Any]]:
        self.asked.append((event_type, len(symbols)))
        if self.feed_fail:
            raise self.feed_fail
        source = self.quotes if event_type == "Quote" else self.summaries
        return {s: source[s] for s in symbols if s in source}


@pytest.fixture
def account(monkeypatch: pytest.MonkeyPatch) -> _Account:
    fake = _Account()
    monkeypatch.setattr(lc.tt, "get", fake.get)
    monkeypatch.setattr(wc.tt, "is_configured", lambda: True)
    monkeypatch.setattr(wc.dxlink, "fetch_once", fake.fetch_once)
    monkeypatch.setattr(wc.options_chain, "risk_free_rate", lambda: (RATE, False))
    monkeypatch.setattr(wc, "_now", lambda: NOW)
    clock = [1000.0]
    monkeypatch.setattr(wc, "_clock", lambda: clock[0])
    fake.clock = clock  # type: ignore[attr-defined]
    lc.reset()
    wc.reset()
    yield fake
    lc.reset()
    wc.reset()


async def test_every_expiry_to_four_months_reads_like_the_delayed_chain(account: _Account) -> None:
    whole = await wc.whole_chain("XYZ")
    assert [e.expiry for e in whole.expiries] == EXPIRIES[:3]  # June is past MAX_DAYS
    assert all(e.atm_iv == pytest.approx(VOL, abs=0.01) for e in whole.expiries)  # our own IVs from the mids
    assert all(e.max_pain is not None and e.net_gex is not None for e in whole.expiries)
    assert whole.spot == SPOT and whole.source == "tastytrade" and whole.max_days == wc.MAX_DAYS
    assert whole.quoted_at == NOW  # real-time quotes: now, in a session
    assert whole.updated_at is not None


async def test_only_strikes_near_the_price_are_asked_for(account: _Account) -> None:
    whole = await wc.whole_chain("XYZ")
    near = [k for k in STRIKES if abs(k / SPOT - 1) <= wc.STRIKE_RANGE]
    assert account.asked == [("Quote", 3 * 2 * len(near)), ("Summary", 3 * 2 * len(near))]
    assert whole.options_read == whole.options_quoted == 3 * 2 * len(near)


async def test_the_positioning_adds_up_every_expiry(account: _Account) -> None:
    whole = await wc.whole_chain("XYZ")
    near = [k for k in STRIKES if abs(k / SPOT - 1) <= wc.STRIKE_RANGE]
    p = whole.positioning
    assert p.call_open_interest == 3 * 1000 * len(near) and p.put_open_interest == 3 * 800 * len(near)
    assert p.max_pain is None and p.call_wall is not None and p.put_wall is not None
    assert all(abs(r.strike / SPOT - 1) <= wc.SHOWN_RANGE for r in p.exposure)


async def test_an_expiry_without_usable_quotes_is_named(account: _Account) -> None:
    for name in [n for n in account.quotes if n.startswith(".XYZ261218")]:
        del account.quotes[name]
    whole = await wc.whole_chain("XYZ")
    assert [e.expiry for e in whole.expiries] == [EXPIRIES[0], EXPIRIES[2]]
    assert whole.left_out == [EXPIRIES[1]]


async def test_a_chain_too_big_for_one_read_keeps_the_nearest_expiries(
    account: _Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    near = [k for k in STRIKES if abs(k / SPOT - 1) <= wc.STRIKE_RANGE]
    monkeypatch.setattr(wc, "MAX_OPTIONS", 2 * 2 * len(near))  # two expiries' worth
    whole = await wc.whole_chain("XYZ")
    assert [e.expiry for e in whole.expiries] == EXPIRIES[:2] and whole.capped is True


async def test_a_symbol_without_options_is_said_so(account: _Account) -> None:
    with pytest.raises(wc.NoOptions):
        await wc.whole_chain("ABC")


@pytest.mark.parametrize("symbol", ["XYZ,SPY", "X{=d}", "", "A/B/C"])
async def test_the_service_checks_the_symbol_itself(account: _Account, symbol: str) -> None:
    with pytest.raises(wc.NoOptions):
        await wc.whole_chain(symbol)
    assert account.calls == [] and account.asked == []


async def test_tastytrade_failing_is_said_with_the_reason(account: _Account) -> None:
    account.fail = tt.TastytradeUnavailable("tastytrade answered 503")
    with pytest.raises(wc.WholeChainUnavailable, match="503"):
        await wc.whole_chain("XYZ")


async def test_the_feed_failing_is_said_with_the_reason(account: _Account) -> None:
    account.feed_fail = dxlink.DxlinkError("the feed refused the subscription")
    with pytest.raises(wc.WholeChainUnavailable, match="feed"):
        await wc.whole_chain("XYZ")


async def test_without_tastytrade_it_says_why(account: _Account, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wc.tt, "is_configured", lambda: False)
    with pytest.raises(wc.WholeChainUnavailable, match="isn't set up"):
        await wc.whole_chain("XYZ")


async def test_a_second_look_within_a_minute_asks_nothing(account: _Account) -> None:
    await wc.whole_chain("XYZ")
    await wc.whole_chain("XYZ")
    assert len(account.asked) == 2
    account.clock[0] += wc.CACHE_SECONDS + 1  # type: ignore[attr-defined]
    await wc.whole_chain("XYZ")
    assert len(account.asked) == 4


async def test_only_the_last_few_symbols_are_kept(account: _Account, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(wc, "MAX_SYMBOLS", 1)
    await wc.whole_chain("XYZ")
    with pytest.raises(wc.NoOptions):
        await wc.whole_chain("ABC")  # not kept: only builds are
    assert list(wc._kept) == ["XYZ"]


def test_the_whole_chain_is_never_written_to_the_database() -> None:
    with open(wc.__file__, encoding="utf-8") as fh:
        source = fh.read()
    assert "AsyncSession" not in source and "SessionLocal" not in source


# ── the route ───────────────────────────────────────────────────────────


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


async def test_the_route_serves_the_whole_chain_to_the_owner_only(account: _Account, owner: dict[str, str]) -> None:
    path = "/v1/owner/options/xyz/chain"
    assert (await _get(path, {})).status_code == 403
    resp = await _get(path, owner)
    assert resp.status_code == 200 and resp.headers["Cache-Control"] == "no-store"
    assert len(resp.json()["expiries"]) == 3
    for bad in ("not!a!ticker", "A-B-C", "A."):
        assert (await _get(f"/v1/owner/options/{bad}/chain", owner)).status_code == 422, bad


async def test_no_options_is_a_422_not_a_404(account: _Account, owner: dict[str, str]) -> None:
    resp = await _get("/v1/owner/options/ABC/chain", owner)
    assert resp.status_code == 422 and "no options" in resp.json()["title"]


async def test_the_route_is_a_503_with_the_reason(account: _Account, owner: dict[str, str]) -> None:
    account.feed_fail = dxlink.DxlinkError("the feed refused the subscription")
    resp = await _get("/v1/owner/options/XYZ/chain", owner)
    assert resp.status_code == 503 and "feed" in resp.json()["title"]
