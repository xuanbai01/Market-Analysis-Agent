"""Dev only: the API with a made-up tastytrade account, for looking at the
owner pages (``/positions``) without the owner's data (ADR 0009: a Claude
session must not see it).

Runs the real app on :8000, with tastytrade's answers taken from fixtures
below (a covered call on NVDA and a long SPY put, nothing anyone holds), the
owner key set to a throwaway value, and no shared secret. Option chains and
prices come from Yahoo as usual, so the context around the positions is
real; with no database, the stored IV history is just missing. Never run it
with production settings.

    uv run python scripts/fake_owner_api.py

then the frontend dev server; in the browser set localStorage
``market-agent.auth-token`` to any value (no shared secret is set) and
unlock ``/positions`` with ``FAKE_OWNER_KEY``.
"""
from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FAKE_OWNER_KEY = "o" * 40
EXPIRY = "2026-12-18"  # a monthly expiry Yahoo lists for both tickers
os.environ["OWNER_KEY"] = FAKE_OWNER_KEY
os.environ["BACKEND_SHARED_SECRET"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import uvicorn  # noqa: E402

from app.api.v1.routers import market as market_router  # noqa: E402
from app.main import app  # noqa: E402
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


async def fake_get(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
    if path == "/customers/me/accounts":
        return {"data": {"items": [{"account": {"account-number": ACCOUNT}}]}}
    if path == f"/accounts/{ACCOUNT}/positions":
        return {"data": {"items": POSITIONS}}
    if path == "/market-data/by-type":
        asked = [s for value in (params or {}).values() for s in str(value).split(",")]
        return {"data": {"items": [QUOTES[s] for s in asked if s in QUOTES]}}
    raise tt.TastytradeNotFound(path)


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


tt.get = fake_get  # type: ignore[assignment]
tt.is_configured = lambda: True  # type: ignore[assignment]
market_router.get_prices_with_cache = prices_from_yahoo  # type: ignore[assignment]

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
