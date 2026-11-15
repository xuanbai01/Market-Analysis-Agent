"""The IV snapshot table on a real Postgres (ADR 0008): the first good
row for a (symbol, trading day) wins, and a re-run writes nothing."""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import settings as settings_module
from app.db.models.options import OptionIvSnapshot, OptionsTracked
from app.services import options_snapshot_store as store
from app.services import options_snapshots as snaps

FRIDAY = date(2026, 11, 13)


def _row(symbol: str, trade_date: date = FRIDAY, iv30: float = 0.25) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "trade_date": trade_date,
        "as_of": datetime(2026, 11, 13, 21, tzinfo=UTC),
        "method_version": 1,
        "spot": 100.0,
        "rate": 0.04,
        "iv30": iv30,
        "iv30_extrapolated": False,
        "iv90": 0.24,
        "iv90_extrapolated": False,
        "skew25": 0.05,
        "rv20": 0.2,
        "rv60": 0.18,
        "call_open_interest": 10,
        "put_open_interest": 12,
        "call_volume": 3,
        "put_volume": 4,
        "next_earnings": None,
        "detail": {"method_version": 1, "expiries": []},
    }


async def test_the_first_row_for_a_session_wins(db_session: AsyncSession) -> None:
    assert await store.insert_snapshot(db_session, _row("SPY", iv30=0.15)) is True
    assert await store.insert_snapshot(db_session, _row("SPY", iv30=0.99)) is False
    rows = (await db_session.execute(select(OptionIvSnapshot))).scalars().all()
    assert [(r.symbol, r.iv30) for r in rows] == [("SPY", 0.15)]


async def test_stored_symbols_reads_one_session(db_session: AsyncSession) -> None:
    await store.insert_snapshot(db_session, _row("SPY"))
    await store.insert_snapshot(db_session, _row("QQQ", trade_date=FRIDAY - timedelta(days=1)))
    assert await store.stored_symbols(db_session, FRIDAY) == {"SPY"}


async def test_tracked_symbols_are_the_recent_ones(db_session: AsyncSession) -> None:
    now = datetime(2026, 11, 14, tzinfo=UTC)
    db_session.add_all([
        OptionsTracked(symbol="AAPL", last_viewed=now - timedelta(days=2)),
        OptionsTracked(symbol="KO", last_viewed=now - timedelta(days=90)),
    ])
    await db_session.commit()
    assert await store.tracked_symbols(db_session, now - timedelta(days=60)) == ["AAPL"]


async def test_the_route_writes_rows_end_to_end(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Yahoo faked; the route, the run and the table are real."""
    monkeypatch.setattr(settings_module.settings, "OPTIONS_SNAPSHOT_SYMBOLS", "SPY,QQQ")
    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", "")
    monkeypatch.setattr(snaps.options_chain, "risk_free_rate", lambda: (0.04, False))
    monkeypatch.setattr(snaps, "snapshot_one", lambda symbol, *_a: ("ok", _row(symbol)))
    monkeypatch.setattr(snaps, "_now", lambda: datetime(2026, 11, 14, 17, tzinfo=UTC))

    first = await client.post("/v1/options/snapshots")
    again = await client.post("/v1/options/snapshots")

    assert first.status_code == 200
    assert first.json()["written"] == ["SPY", "QQQ"]
    assert again.json()["status"] == "no_new_session"
    rows = (await db_session.execute(select(OptionIvSnapshot.symbol))).scalars().all()
    assert sorted(rows) == ["QQQ", "SPY"]


async def test_iv30_history_reads_one_method_oldest_first(db_session: AsyncSession) -> None:
    """Rows of another method version are left out: the rank compares like with like."""
    await store.insert_snapshot(db_session, _row("SPY", FRIDAY - timedelta(days=1), iv30=0.14))
    await store.insert_snapshot(db_session, _row("SPY", FRIDAY, iv30=0.15))
    await store.insert_snapshot(db_session, {**_row("SPY", FRIDAY - timedelta(days=2), iv30=0.99), "method_version": 2})
    await store.insert_snapshot(db_session, {**_row("SPY", FRIDAY - timedelta(days=3)), "iv30": None})
    await store.insert_snapshot(db_session, _row("QQQ", FRIDAY, iv30=0.25))
    assert await store.iv30_history(db_session, "SPY", 1) == [(FRIDAY - timedelta(days=1), 0.14), (FRIDAY, 0.15)]


async def test_touch_tracked_upserts_the_last_view(db_session: AsyncSession) -> None:
    first, later = datetime(2026, 11, 14, tzinfo=UTC), datetime(2026, 11, 15, tzinfo=UTC)
    await store.touch_tracked(db_session, "AAPL", first)
    await store.touch_tracked(db_session, "AAPL", later)
    rows = (await db_session.execute(select(OptionsTracked))).scalars().all()
    assert [(r.symbol, r.last_viewed) for r in rows] == [("AAPL", later)]
