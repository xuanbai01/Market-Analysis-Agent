"""The trade copy's table (``owner_transactions``) against a real Postgres:
a row is written once, and the only update is a row stored with estimated
fees taking the final figures."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import owner_trade_store as store


def _row(tid: int, estimated: bool = False, blob: bytes = b"sealed") -> dict[str, object]:
    return {"id": tid, "key_version": 1, "nonce": b"\x00" * 12, "ciphertext": blob, "estimated_fee": estimated}


async def test_rows_are_written_once(db_session: AsyncSession) -> None:
    assert await store.insert(db_session, [_row(1), _row(2)]) == 2
    assert await store.insert(db_session, [_row(2, blob=b"other"), _row(3)]) == 1
    rows = await store.stored(db_session)
    assert [r.id for r in rows] == [1, 2, 3]
    assert next(r for r in rows if r.id == 2).ciphertext == b"sealed"  # the first write stands


async def test_a_first_sync_larger_than_one_statement_takes_is_written_in_chunks(db_session: AsyncSession) -> None:
    """Postgres takes at most 32,767 parameters a statement: 6,000 rows of 5
    in one would fail every time (PR 4's security review)."""
    assert await store.insert(db_session, [_row(i) for i in range(1, 6001)]) == 6000
    assert len(await store.stored(db_session)) == 6000


async def test_nothing_to_insert_writes_nothing(db_session: AsyncSession) -> None:
    assert await store.insert(db_session, []) == 0


async def test_only_a_row_with_estimated_fees_is_replaced(db_session: AsyncSession) -> None:
    await store.insert(db_session, [_row(1, estimated=True), _row(2)])
    assert await store.replace_estimated(db_session, _row(1, blob=b"final")) is True
    assert await store.replace_estimated(db_session, _row(2, blob=b"changed")) is False
    rows = {r.id: r for r in await store.stored(db_session)}
    assert (rows[1].ciphertext, rows[1].estimated_fee) == (b"final", False)
    assert rows[2].ciphertext == b"sealed"
