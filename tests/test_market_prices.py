"""
Tests for the Phase 4.1 prices route — `GET /v1/market/{symbol}/prices`.

The route is the data feed for the dashboard's hero price chart. Two
behaviors:

1. **Read-through cache:** if `candles` already contains rows covering
   the requested range for the symbol, return them directly (no
   yfinance call). Halves yfinance load on dogfood traffic.
2. **Cache miss → ingest → return:** if data is missing or stale, fetch
   via the existing `ingest_market_data` path (which upserts into
   `candles`), then return the freshly-cached rows.

The route is auth-gated by ``require_shared_secret`` — the dashboard
already authenticates so adding the gate now keeps the surface
consistent.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.candles import Candle
from app.db.models.symbols import Symbol
from app.services.data_ingestion import PROVIDERS


async def _seed_candles(
    db: AsyncSession,
    symbol: str,
    *,
    days: int,
    end: datetime | None = None,
) -> None:
    """Insert ``days`` daily candles ending at ``end`` (default: now)."""
    end = end or datetime.now(UTC)
    db.add(Symbol(symbol=symbol, name=f"{symbol} test"))
    await db.flush()
    rows = [
        Candle(
            symbol=symbol,
            ts=end - timedelta(days=days - 1 - i),
            interval="1d",
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("99"),
            close=Decimal("100") + Decimal(i),
            volume=1_000_000 + i * 1000,
        )
        for i in range(days)
    ]
    db.add_all(rows)
    await db.flush()


# ── Range parsing ────────────────────────────────────────────────────


async def test_prices_rejects_unknown_range(client: AsyncClient) -> None:
    """Range param must be one of 60D / 1Y / 5Y for 4.1."""
    resp = await client.get("/v1/market/NVDA/prices?range=banana")
    assert resp.status_code == 422


async def test_prices_default_range_is_60d(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """No range param → 60-day default."""
    await _seed_candles(db_session, "NVDA", days=80)
    resp = await client.get("/v1/market/NVDA/prices")
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == "60D"


# ── Read-through cache ───────────────────────────────────────────────


async def test_prices_serves_from_candles_when_data_exists(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If candles has 60D coverage, the route doesn't call yfinance."""
    await _seed_candles(db_session, "NVDA", days=70)

    # Spy on the provider — should NOT be invoked.
    called = {"count": 0}

    def _spy(*_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        called["count"] += 1
        return []

    monkeypatch.setitem(PROVIDERS, "yfinance", _spy)

    resp = await client.get("/v1/market/NVDA/prices?range=60D")
    assert resp.status_code == 200
    assert called["count"] == 0, "yfinance should not be called when cache covers the range"


async def test_prices_calls_yfinance_on_cache_miss(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty cache → yfinance fetch → upsert → return."""
    db_session.add(Symbol(symbol="NVDA", name="NVIDIA"))
    await db_session.flush()

    now = datetime.now(UTC)
    fake_bars = [
        {
            "ts": now - timedelta(days=i),
            "open": Decimal("100"),
            "high": Decimal("105"),
            "low": Decimal("99"),
            "close": Decimal("102"),
            "volume": 1_000_000,
        }
        for i in range(60)
    ]

    def _fake_yf(_symbol: str, _period: str) -> list[dict[str, Any]]:
        return fake_bars

    monkeypatch.setitem(PROVIDERS, "yfinance", _fake_yf)

    resp = await client.get("/v1/market/NVDA/prices?range=60D")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["prices"]) >= 50, (
        f"expected ~60 bars after yfinance fetch + cache write, got "
        f"{len(body['prices'])}"
    )


# ── Response shape ───────────────────────────────────────────────────


async def test_prices_response_shape(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _seed_candles(db_session, "NVDA", days=70)
    resp = await client.get("/v1/market/NVDA/prices?range=60D")
    body = resp.json()
    assert body["ticker"] == "NVDA"
    assert body["range"] == "60D"
    assert isinstance(body["prices"], list)
    assert len(body["prices"]) > 0
    first = body["prices"][0]
    assert {"ts", "close", "volume"}.issubset(first.keys())
    # latest summary
    assert "latest" in body
    assert "close" in body["latest"]
    assert "delta_abs" in body["latest"]
    assert "delta_pct" in body["latest"]


async def test_prices_latest_delta_computed_from_last_two_closes(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Spot-check the delta math: last close 161, prev close 160 → +1, +0.625%."""
    db_session.add(Symbol(symbol="NVDA", name="NVIDIA"))
    await db_session.flush()
    now = datetime.now(UTC)
    db_session.add_all(
        [
            Candle(
                symbol="NVDA",
                ts=now - timedelta(days=1),
                interval="1d",
                open=Decimal("160"),
                high=Decimal("162"),
                low=Decimal("158"),
                close=Decimal("160"),
                volume=1_000_000,
            ),
            Candle(
                symbol="NVDA",
                ts=now,
                interval="1d",
                open=Decimal("160"),
                high=Decimal("162"),
                low=Decimal("159"),
                close=Decimal("161"),
                volume=1_000_000,
            ),
        ]
    )
    await db_session.flush()
    resp = await client.get("/v1/market/NVDA/prices?range=60D")
    body = resp.json()
    assert body["latest"]["close"] == pytest.approx(161.0)
    assert body["latest"]["delta_abs"] == pytest.approx(1.0)
    assert body["latest"]["delta_pct"] == pytest.approx(1.0 / 160.0)


# ── Symbol normalization ─────────────────────────────────────────────


async def test_prices_uppercases_symbol(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add(Symbol(symbol="NVDA", name="NVIDIA"))
    await db_session.flush()

    seen: list[str] = []

    def _capture(symbol: str, _period: str) -> list[dict[str, Any]]:
        seen.append(symbol)
        return []

    monkeypatch.setitem(PROVIDERS, "yfinance", _capture)

    resp = await client.get("/v1/market/nvda/prices?range=60D")
    assert resp.status_code == 200
    assert seen == ["NVDA"]


# ── 1Y / 5Y ranges ───────────────────────────────────────────────────


@pytest.mark.parametrize("range_str", ["60D", "1Y", "5Y"])
async def test_prices_accepts_supported_ranges(
    client: AsyncClient, db_session: AsyncSession, range_str: str
) -> None:
    """All three Phase-4.1 ranges return 200; data depth differs."""
    # Seed 5Y of data so all three ranges have cache coverage.
    await _seed_candles(db_session, "NVDA", days=5 * 365)
    resp = await client.get(f"/v1/market/NVDA/prices?range={range_str}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == range_str
