"""Reads and writes for the owner's trade copy (``owner_transactions``).
Rows arrive sealed: nothing here sees a trade in the clear, and the log
lines carry counts only."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.observability import log_external_call
from app.db.models.owner import OwnerTransaction


async def stored(session: AsyncSession) -> list[OwnerTransaction]:
    """Every stored row, oldest id first."""
    result = await session.execute(select(OwnerTransaction).order_by(OwnerTransaction.id))
    return list(result.scalars().all())


async def insert(session: AsyncSession, rows: list[dict[str, Any]]) -> int:
    """Add sealed rows; one already stored is left as it was. Returns how many were written."""
    if not rows:
        return 0
    with log_external_call("db.owner_transactions.insert", {"rows": len(rows)}) as call:
        now = datetime.now(UTC)
        stmt = pg_insert(OwnerTransaction).values([{**row, "stored_at": now} for row in rows]).on_conflict_do_nothing(
            index_elements=[OwnerTransaction.id]
        )
        result = await session.execute(stmt)
        await session.commit()
        written = int(result.rowcount or 0)
        call.record_output({"written": written})
    return written


async def replace_estimated(session: AsyncSession, row: dict[str, Any]) -> bool:
    """The one update allowed: a row stored while its fees were estimated
    takes the final figures. A row already final is left alone."""
    with log_external_call("db.owner_transactions.replace", {"rows": 1}) as call:
        stmt = (
            update(OwnerTransaction)
            .where(OwnerTransaction.id == row["id"], OwnerTransaction.estimated_fee.is_(True))
            .values(**{k: v for k, v in row.items() if k != "id"}, stored_at=datetime.now(UTC))
        )
        result = await session.execute(stmt)
        await session.commit()
        replaced = bool(result.rowcount)
        call.record_output({"replaced": replaced})
    return replaced
