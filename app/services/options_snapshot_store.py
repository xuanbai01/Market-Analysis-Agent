"""
Reads and writes for the IV snapshot table (ADR 0008).

Each write commits on its own: the run holds no connection while it
fetches from Yahoo between writes (CLAUDE.md: a request holds no database
connection while slow work runs).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import log_external_call
from app.db.models.options import OptionIvSnapshot, OptionsTracked


async def stored_symbols(session: AsyncSession, trade_date: date) -> set[str]:
    with log_external_call("db.option_iv_snapshots.stored", {"trade_date": trade_date.isoformat()}) as call:
        result = await session.execute(
            select(OptionIvSnapshot.symbol).where(OptionIvSnapshot.trade_date == trade_date)
        )
        symbols = set(result.scalars().all())
        call.record_output({"count": len(symbols)})
    return symbols


async def tracked_symbols(session: AsyncSession, since: datetime) -> list[str]:
    """Symbols whose options page was opened since ``since``, most recent first."""
    result = await session.execute(
        select(OptionsTracked.symbol)
        .where(OptionsTracked.last_viewed >= since)
        .order_by(OptionsTracked.last_viewed.desc())
    )
    return list(result.scalars().all())


async def insert_snapshot(session: AsyncSession, row: dict[str, Any]) -> bool:
    """Write one snapshot; False when the (symbol, trading day) is already
    stored, in which case the stored row is left as it was."""
    with log_external_call(
        "db.option_iv_snapshots.insert", {"symbol": row["symbol"], "trade_date": row["trade_date"].isoformat()}
    ) as call:
        stmt = pg_insert(OptionIvSnapshot).values(**row).on_conflict_do_nothing(
            index_elements=[OptionIvSnapshot.symbol, OptionIvSnapshot.trade_date]
        )
        result = await session.execute(stmt)
        await session.commit()
        written = bool(result.rowcount)
        call.record_output({"written": written})
    return written


async def iv30_history(session: AsyncSession, symbol: str, method_version: int) -> list[tuple[date, float]]:
    """``symbol``'s stored IV30s made by ``method_version``, oldest first."""
    result = await session.execute(
        select(OptionIvSnapshot.trade_date, OptionIvSnapshot.iv30)
        .where(
            OptionIvSnapshot.symbol == symbol,
            OptionIvSnapshot.method_version == method_version,
            OptionIvSnapshot.iv30.is_not(None),
        )
        .order_by(OptionIvSnapshot.trade_date)
    )
    return [(d, float(v)) for d, v in result.all()]


async def touch_tracked(session: AsyncSession, symbol: str, at: datetime) -> None:
    """Record that ``symbol``'s options page was opened; the daily run
    snapshots it for 60 days after."""
    stmt = pg_insert(OptionsTracked).values(symbol=symbol, last_viewed=at)
    stmt = stmt.on_conflict_do_update(index_elements=[OptionsTracked.symbol], set_={"last_viewed": stmt.excluded.last_viewed})
    await session.execute(stmt)
    await session.commit()

