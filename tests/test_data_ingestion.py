"""
Tests for ingestion. Register a fake provider via `monkeypatch.setitem`
so none of these actually call yfinance — that would make the suite
flaky, slow, and dependent on an external service.
"""
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.candles import Candle
from app.db.models.symbols import Symbol
from app.services.data_ingestion import PROVIDERS, ingest_market_data


def _fake_bars(count: int = 3, base_close: float = 100.0) -> list[dict]:
    base = datetime(2026, 4, 1, tzinfo=UTC)
    return [
        {
            "ts": base + timedelta(days=i),
            "open": Decimal(str(base_close + i - 0.5)),
            "high": Decimal(str(base_close + i + 0.5)),
            "low": Decimal(str(base_close + i - 1.0)),
            "close": Decimal(str(base_close + i)),
            "volume": 1_000_000 + i,
        }
        for i in range(count)
    ]


async def _seed_symbol(session: AsyncSession, symbol: str) -> None:
    session.add(Symbol(symbol=symbol, name=f"{symbol} test"))
    await session.flush()


async def test_ingest_writes_rows_and_returns_count(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_symbol(db_session, "NVDA")
    bars = _fake_bars(count=3)
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym, _period: bars)

    count = await ingest_market_data(db_session, "NVDA", "1mo", "fake")
    assert count == 3

    rows = (
        await db_session.execute(select(Candle).where(Candle.symbol == "NVDA"))
    ).scalars().all()
    assert len(rows) == 3
    assert {float(r.close) for r in rows} == {100.0, 101.0, 102.0}


async def test_ingest_upserts_on_conflict(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Calling the same provider twice with the same ts must not double-insert."""
    await _seed_symbol(db_session, "NVDA")
    bars = _fake_bars(count=2, base_close=100.0)
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym, _period: bars)

    await ingest_market_data(db_session, "NVDA", "1mo", "fake")
    # Same timestamps, different close — simulates provider restating a bar.
    restated = _fake_bars(count=2, base_close=200.0)
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym, _period: restated)
    await ingest_market_data(db_session, "NVDA", "1mo", "fake")

    rows = (
        await db_session.execute(select(Candle).where(Candle.symbol == "NVDA"))
    ).scalars().all()
    assert len(rows) == 2, "expected upsert, got duplicate inserts"
    closes = sorted(float(r.close) for r in rows)
    assert closes == [200.0, 201.0], "expected restated close values to overwrite originals"


async def test_ingest_empty_provider_returns_zero(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _seed_symbol(db_session, "NVDA")
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym, _period: [])

    count = await ingest_market_data(db_session, "NVDA", "1mo", "fake")
    assert count == 0


async def test_ingest_unknown_provider_raises(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="Unknown provider"):
        await ingest_market_data(db_session, "NVDA", "1mo", "not-registered")


async def test_ingest_logs_external_call(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    await _seed_symbol(db_session, "NVDA")
    bars = _fake_bars(count=2)
    monkeypatch.setitem(PROVIDERS, "fake", lambda _sym, _period: bars)

    with caplog.at_level(logging.INFO, logger="app.external"):
        await ingest_market_data(db_session, "NVDA", "1mo", "fake")

    records = [r for r in caplog.records if r.name == "app.external"]
    assert len(records) == 1
    r = records[0]
    assert r.service_id == "fake.history"
    assert r.input_summary == {"symbol": "NVDA", "period": "1mo", "interval": "1d"}
    assert r.output_summary == {"bar_count": 2}
    assert r.outcome == "ok"
