"""End-to-end tests for the market router. Seed candles via db_session, then
hit the HTTP endpoint through the ASGI transport."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.candles import Candle
from app.db.models.symbols import Symbol
from app.services.data_ingestion import PROVIDERS


async def test_market_latest_returns_404_when_no_bars(client: AsyncClient) -> None:
    resp = await client.get("/v1/market/NVDA")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


async def test_market_latest_returns_real_bar(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(Symbol(symbol="NVDA", name="NVIDIA Corp"))
    await db_session.flush()  # FK must exist before inserting Candles
    now = datetime.now(UTC)
    db_session.add_all(
        [
            Candle(
                symbol="NVDA",
                ts=now - timedelta(days=1),
                interval="1d",
                open=Decimal("900"),
                high=Decimal("910"),
                low=Decimal("895"),
                close=Decimal("905"),
                volume=1_000_000,
            ),
            Candle(
                symbol="NVDA",
                ts=now,
                interval="1d",
                open=Decimal("950"),
                high=Decimal("1010"),
                low=Decimal("945"),
                close=Decimal("1000"),
                volume=2_000_000,
            ),
        ]
    )
    await db_session.flush()

    resp = await client.get("/v1/market/NVDA")
    assert resp.status_code == 200
    body = resp.json()
    assert body["symbol"] == "NVDA"
    # Must be the newest bar, not the fake 1.0 stub that used to live here.
    assert body["ohlcv"]["c"] == 1000.0
    assert body["ohlcv"]["v"] == 2_000_000.0
    assert body["technicals"] == {"rsi": None, "sma20": None, "sma50": None, "sma200": None}


async def test_market_history_empty_by_default(client: AsyncClient) -> None:
    resp = await client.get("/v1/market/NVDA/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"symbol": "NVDA", "interval": "1d", "bars": []}


async def test_market_ingest_drives_fake_provider_into_db(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_session.add(Symbol(symbol="NVDA", name="NVIDIA Corp"))
    await db_session.flush()

    base = datetime(2026, 4, 1, tzinfo=UTC)
    bars = [
        {
            "ts": base + timedelta(days=i),
            "open": Decimal("100"),
            "high": Decimal("102"),
            "low": Decimal("99"),
            "close": Decimal(str(100 + i)),
            "volume": 500_000,
        }
        for i in range(3)
    ]
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym, _period: bars)

    resp = await client.post(
        "/v1/market/ingest",
        json={"symbol": "NVDA", "period": "1mo", "provider": "fake"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"job_id": "local-inline", "ingested": 3, "symbol": "NVDA"}

    # Ingested rows should be readable via /history now.
    hist = await client.get("/v1/market/NVDA/history")
    closes = [b["c"] for b in hist.json()["bars"]]
    assert closes == [100.0, 101.0, 102.0]
