"""Dev only: the API with a made-up tastytrade account, for looking at the
owner pages (``/positions``, ``/trades``) without the owner's data (ADR 0009:
a Claude session must not see it).

Runs the real app on 127.0.0.1:8000, with tastytrade's answers taken from
fixtures below (a covered call on NVDA and a long SPY put, nothing anyone
holds), and ``/trades`` from a made-up history (an expiry, a vertical, an
assignment, a roll, an open put, a close with nothing to match) in place of
the encrypted copy. Whatever ``.env`` says, it runs with a throwaway shared secret and
owner key, no LLM, news, FRED or tastytrade keys, and a database address
nothing listens on, so it can't spend, write anywhere or reach the real
account; it refuses to start on Fly. Option chains and prices come from
Yahoo as usual, so the context around the positions is real; the stored IV
history is just missing.

    uv run python scripts/fake_owner_api.py

then the frontend dev server; in the browser set localStorage
``market-agent.auth-token`` to ``FAKE_SHARED_SECRET`` and unlock
``/positions`` with ``FAKE_OWNER_KEY``. The options page's IV history
panel reads made-up candles and metrics for any ticker.
"""
from __future__ import annotations

import math
import os
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

FAKE_SHARED_SECRET = "local-dev"
FAKE_OWNER_KEY = "o" * 40  # plainly fake
if os.environ.get("FLY_APP_NAME") or os.environ.get("APP_ENV") == "prod":
    sys.exit("fake_owner_api is for a developer's machine, never a deployed app")
# Environment variables beat .env in pydantic-settings: every secret and
# address that could reach something real is overridden here.
os.environ.update({
    "BACKEND_SHARED_SECRET": FAKE_SHARED_SECRET,
    "OWNER_KEY": FAKE_OWNER_KEY,
    "OWNER_VAULT_KEY": "",
    "DATABASE_URL": "postgresql+asyncpg://nobody:nothing@127.0.0.1:9/none",
    "ANTHROPIC_API_KEY": "",
    "DEEPSEEK_API_KEY": "",
    "NEWSAPI_KEY": "",
    "FRED_API_KEY": "",
    "TASTYTRADE_CLIENT_ID": "",
    "TASTYTRADE_CLIENT_SECRET": "",
    "TASTYTRADE_REFRESH_TOKEN": "",
})

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402

from app.api.v1.routers import market as market_router  # noqa: E402
from app.api.v1.routers import owner as owner_router  # noqa: E402
from app.main import app  # noqa: E402
from app.schemas.owner import OwnerTrade  # noqa: E402
from app.services import dxlink  # noqa: E402
from app.services import tastytrade_client as tt  # noqa: E402

ACCOUNT = "FAKE0001"


def _quote(symbol: str, mark: float, **greeks: float) -> dict[str, Any]:
    return {
        "symbol": symbol, "bid": round(mark - 0.05, 2), "ask": round(mark + 0.05, 2), "mark": mark,
        "updated-at": datetime.now(UTC).isoformat(), **greeks,
    }


POSITIONS = [
    {"symbol": "NVDA", "instrument-type": "Equity", "underlying-symbol": "NVDA", "quantity": "100",
     "quantity-direction": "Long", "average-open-price": "150.00", "multiplier": 1},
    {"symbol": "NVDA  261218C00175000", "instrument-type": "Equity Option", "underlying-symbol": "NVDA", "quantity": "1",
     "quantity-direction": "Short", "average-open-price": "4.80", "multiplier": 100},
    {"symbol": "SPY   261218P00640000", "instrument-type": "Equity Option", "underlying-symbol": "SPY", "quantity": "2",
     "quantity-direction": "Long", "average-open-price": "6.10", "multiplier": 100},
    {"symbol": "/ESZ6", "instrument-type": "Future", "underlying-symbol": "/ES", "quantity": "1",
     "quantity-direction": "Long", "average-open-price": "6800", "multiplier": 50},
]
QUOTES = {
    "NVDA": _quote("NVDA", 162.85),
    "SPY": _quote("SPY", 671.0),
    "NVDA  261218C00175000": _quote("NVDA  261218C00175000", 4.05, volatility=0.55, delta=0.33, gamma=0.016, theta=-0.11, vega=0.21),
    "SPY   261218P00640000": _quote("SPY   261218P00640000", 5.2, volatility=0.17, delta=-0.24, gamma=0.006, theta=-0.13, vega=0.68),
}


# A made-up NVDA chain for the options page's Live switch: one expiry, quotes
# priced by Black-76 on a gently skewed smile around the fake price.
CHAIN_EXPIRY = date(2026, 12, 18)
CHAIN_STRIKES = [120.0 + 2.5 * i for i in range(41)]  # 120 to 220


def _occ(kind: str, strike: float) -> str:
    return f"NVDA  {CHAIN_EXPIRY:%y%m%d}{kind}{int(strike * 1000):08d}"


def _chain_quote(symbol: str) -> dict[str, Any] | None:
    from app.services import options_math as om  # noqa: PLC0415

    match = next(((k, kind) for k in CHAIN_STRIKES for kind in "CP" if _occ(kind, k) == symbol), None)
    if match is None:
        return None
    strike, kind = match
    spot, years, rate = QUOTES["NVDA"]["mark"], 32 / 365, 0.04
    vol = 0.55 + 0.25 * max(0.0, (spot - strike) / spot)  # puts below the price cost more
    price = om.black76(spot * math.exp(rate * years), strike, years, vol, math.exp(-rate * years), call=kind == "C")
    return {**_quote(symbol, round(price, 2)), "volume": 50, "open-interest": int(4000 * math.exp(-abs(strike - 175) / 15))}


async def fake_get(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
    if path == "/customers/me/accounts":
        return {"data": {"items": [{"account": {"account-number": ACCOUNT}}]}}
    if path == f"/accounts/{ACCOUNT}/positions":
        return {"data": {"items": POSITIONS}}
    if path == "/option-chains/NVDA/nested":
        strikes = [{"strike-price": f"{k:.1f}", "call": _occ("C", k), "put": _occ("P", k)} for k in CHAIN_STRIKES]
        return {"data": {"items": [{"root-symbol": "NVDA", "shares-per-contract": 100,
                                    "expirations": [{"expiration-date": CHAIN_EXPIRY.isoformat(), "strikes": strikes}]}]}}
    if path == "/market-data/by-type":
        asked = [s for value in (params or {}).values() for s in str(value).split(",")]
        items = [QUOTES.get(s) or _chain_quote(s) for s in asked]
        return {"data": {"items": [item for item in items if item]}}
    if path == "/market-metrics":
        symbol = str((params or {}).get("symbols", ""))
        return {"data": {"items": [{
            "symbol": symbol, "implied-volatility-index": "0.3412", "implied-volatility-30-day": "34.6",
            "tw-implied-volatility-index-rank": "0.41", "implied-volatility-percentile": "0.55",
            "historical-volatility-30-day": "29.8", "historical-volatility-60-day": "31.2",
            "historical-volatility-90-day": "33.0", "implied-volatility-updated-at": "2026-11-14T20:59:00+00:00",
        }]}}
    raise tt.TastytradeNotFound(path)


async def fake_candles(symbol: str, period: str, from_time: datetime) -> dxlink.CandleHistory:
    """Made-up daily candles from 2016: a drifting, wobbling close and an IV
    that swings between about 25% and 60%. Nothing anyone traded."""
    out = []
    day, close, i = date(2016, 1, 4), 30.0, 0
    while day <= date(2026, 11, 13):
        if day.weekday() < 5:
            close *= math.exp(0.0006 + 0.02 * math.sin(i * 1.7) * math.cos(i * 0.13))
            iv = 0.42 + 0.15 * math.sin(i / 90) + 0.04 * math.sin(i / 7)
            out.append(dxlink.Candle(time=datetime(day.year, day.month, day.day, tzinfo=UTC), open=close, high=close,
                                     low=close, close=round(close, 2), volume=1e6, imp_volatility=round(iv, 4),
                                     open_interest=None))
            i += 1
        day = date.fromordinal(day.toordinal() + 1)
    return dxlink.CandleHistory(candles=tuple(out), complete=True)


async def prices_from_yahoo(_session: Any, symbol: str, range_: str) -> dict[str, Any]:
    """The prices route without the candle table: straight from Yahoo."""
    import yfinance  # noqa: PLC0415

    history = yfinance.Ticker(symbol).history(period="5y" if range_ == "5Y" else "1y", auto_adjust=True)
    points = [
        {"ts": ts.isoformat(), "close": float(close), "volume": float(volume)}
        for ts, close, volume in zip(history.index, history["Close"], history["Volume"], strict=False)
    ]
    last = points[-1]
    return {"ticker": symbol, "range": range_, "prices": points, "latest": {**last, "delta_abs": 0.0, "delta_pct": 0.0}}


def _trade(
    tid: int, day: str, action: str, symbol: str, qty: float, net: float, *, order: int | None = None,
    sub: str | None = None, underlying: str | None = None, fees: float = 0.0,
) -> OwnerTrade:
    stock = " " not in symbol
    return OwnerTrade(
        id=tid, account=1, executed_at=f"{day}T15:{tid % 60:02d}:00+00:00", date=day,
        type="Receive Deliver" if sub else "Trade", sub_type=sub or action, action=action, symbol=symbol,
        underlying=underlying or symbol.split()[0], instrument_type="Equity" if stock else "Equity Option",
        quantity=qty, net_value=net, fees=fees, order_id=order,
    )


TRADES = [
    _trade(1, "2026-08-01", "Buy to Close", "AAPL  260815C00230000", 1, -120.0),  # opened before the copy
    _trade(2, "2026-08-04", "Sell to Open", "SPY   260821P00600000", 1, 208.9, order=101, fees=1.1),
    _trade(3, "2026-08-21", "Buy to Close", "SPY   260821P00600000", 1, 0.0, sub="Expiration"),
    _trade(4, "2026-09-02", "Sell to Open", "NVDA  261016C00190000", 1, 318.9, order=102, fees=1.1),
    _trade(5, "2026-09-02", "Buy to Open", "NVDA  261016C00195000", 1, -161.1, order=102, fees=1.1),
    _trade(6, "2026-10-01", "Buy to Close", "NVDA  261016C00190000", 1, -80.1, order=103, fees=0.1),
    _trade(7, "2026-10-01", "Sell to Close", "NVDA  261016C00195000", 1, 19.9, order=103, fees=0.1),
    _trade(8, "2026-09-15", "Sell to Open", "NVDA  261016P00150000", 1, 248.9, order=104, fees=1.1),
    _trade(9, "2026-10-16", "Buy to Close", "NVDA  261016P00150000", 1, 0.0, sub="Assignment"),
    _trade(10, "2026-10-16", "Buy to Open", "NVDA", 100, -15000.0, sub="Assignment", underlying="NVDA"),
    _trade(11, "2026-10-20", "Sell to Open", "NVDA  261120C00175000", 1, 478.9, order=105, fees=1.1),
    _trade(12, "2026-11-13", "Buy to Close", "NVDA  261120C00175000", 1, -121.1, order=106, fees=1.1),
    _trade(13, "2026-11-13", "Sell to Open", "NVDA  261218C00180000", 1, 308.9, order=106, fees=1.1),
    _trade(14, "2026-11-03", "Buy to Open", "SPY   261218P00640000", 2, -1222.2, order=107, fees=2.2),
]


async def fake_sync(_session: Any) -> None:
    return None


async def fake_list_trades(_session: Any) -> list[OwnerTrade]:
    return sorted(TRADES, key=lambda t: t.executed_at or "", reverse=True)


tt.get = fake_get  # type: ignore[assignment]
dxlink.fetch_candles = fake_candles  # type: ignore[assignment]
owner_router.sync = fake_sync  # type: ignore[assignment]
owner_router.list_trades = fake_list_trades  # type: ignore[assignment]
tt.is_configured = lambda: True  # type: ignore[assignment]
market_router.get_prices_with_cache = prices_from_yahoo  # type: ignore[assignment]

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
