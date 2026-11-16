"""The owner's trade copy (ADR 0009, amended 2026-11-15): their tastytrade
transactions, synced into ``owner_transactions`` sealed by ``owner_vault``,
and listed back for the /trades page and its CSV.

The owner's own transactions are theirs under tastytrade's terms, so a copy
may be kept; the market's data never is. A sync reads the account's
transactions from a week before the newest one stored (so a late fee
correction is seen), adds the new ones and replaces a row only when it was
stored with estimated fees and tastytrade now sends the final ones. No
connection is held while tastytrade is read. Each stored row keeps the
account's 1-based number, never the account number, and only the fields
listed in KEPT. Nothing here goes to a prompt.
"""
from __future__ import annotations

import asyncio
import csv
import io
import logging
import time
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.owner import OwnerTrade
from app.services import owner_positions
from app.services import owner_trade_store as store
from app.services import owner_vault as vault
from app.services import tastytrade_client as tt

logger = logging.getLogger(__name__)

# A sync at most this often, whether the last one worked or not: the page
# can be refreshed freely, and a failing tastytrade isn't asked again and again.
SYNC_EVERY_SECONDS = 60.0
# A sync that runs longer gives up (the next visit starts again from the copy).
SYNC_SECONDS = 120.0
# How far before the newest stored transaction a sync reads again.
OVERLAP_DAYS = 7
PER_PAGE = 2000  # tastytrade's maximum
MAX_PAGES = 25
# The fields a stored transaction keeps (plus the account's number in the list).
KEPT = (
    "executed-at", "transaction-date", "transaction-type", "transaction-sub-type", "description", "action",
    "symbol", "underlying-symbol", "instrument-type", "quantity", "price", "value", "value-effect",
    "commission", "commission-effect", "clearing-fees", "clearing-fees-effect", "regulatory-fees",
    "regulatory-fees-effect", "proprietary-index-option-fees", "proprietary-index-option-fees-effect",
    "net-value", "net-value-effect", "order-id", "reverses-id", "is-estimated-fee",
)
FEES = ("commission", "clearing-fees", "regulatory-fees", "proprietary-index-option-fees")
CSV_COLUMNS = (
    "id", "account", "executed_at", "date", "type", "sub_type", "action", "symbol", "underlying",
    "instrument_type", "quantity", "price", "value", "fees", "net_value", "description",
)
# A cell a spreadsheet would run as a formula (OWASP CSV injection).
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class SyncResult:
    new: int
    replaced: int
    skipped: bool = False


class SyncFailed(Exception):
    """tastytrade couldn't be read, or the sync ran past SYNC_SECONDS: the
    copy stands as it was. The text is safe to show (account paths masked)."""


_synced_at: float | None = None
# Why the last sync failed, until one works: a visit inside the minute
# after it is told so, not that the copy was updated.
_last_failure: str | None = None
_lock = asyncio.Lock()  # one sync at a time


def reset() -> None:
    """Forget when the last sync ran and how (tests)."""
    global _synced_at, _last_failure, _lock
    _synced_at, _last_failure, _lock = None, None, asyncio.Lock()


# Swapped in tests.
def _clock() -> float:
    return time.monotonic()


def _id(item: dict[str, Any]) -> int | None:
    value = item.get("id")
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _scrubbed(value: Any, numbers: dict[str, int]) -> Any:
    """Free text with any account number in it replaced by "account N"."""
    if not isinstance(value, str):
        return value
    for number, index in numbers.items():
        value = value.replace(number, f"account {index}")
    return value


def _sealed(tid: int, item: dict[str, Any], account: int, numbers: dict[str, int]) -> dict[str, Any]:
    payload = {key: _scrubbed(item[key], numbers) for key in KEPT if key in item}
    payload["account"] = account
    estimated = item.get("is-estimated-fee") is True
    nonce, ciphertext = vault.seal(payload, tid, estimated_fee=estimated)
    return {
        "id": tid, "key_version": vault.KEY_VERSION, "nonce": nonce, "ciphertext": ciphertext,
        "estimated_fee": estimated,
    }


def _opened(rows: list[Any]) -> list[tuple[int, dict[str, Any]]]:
    """Every stored row, opened. CPU work: callers run it off the event loop."""
    return [
        (row.id, vault.unseal(row.nonce, row.ciphertext, row.id, key_version=row.key_version, estimated_fee=row.estimated_fee))
        for row in rows
    ]


def _latest_date(payloads: list[dict[str, Any]]) -> date | None:
    days = []
    for payload in payloads:
        try:
            days.append(date.fromisoformat(str(payload.get("transaction-date"))))
        except ValueError:
            continue
    return max(days, default=None)


async def _transactions(number: str, start: date | None) -> list[dict[str, Any]]:
    """One account's transactions from ``start`` on, every page (MAX_PAGES at most)."""
    found: list[dict[str, Any]] = []
    for page in range(MAX_PAGES):
        params: dict[str, Any] = {"per-page": PER_PAGE, "page-offset": page, "sort": "Asc"}
        if start is not None:
            params["start-date"] = start.isoformat()
        payload = await tt.get(f"/accounts/{number}/transactions", params, op="transactions")
        found += owner_positions.items_of(payload, strict=True)
        pagination = payload.get("pagination") if isinstance(payload, dict) else None
        pages = pagination.get("total-pages") if isinstance(pagination, dict) else None
        if not isinstance(pages, int) or page + 1 >= pages:
            break
    return found


async def sync(session: AsyncSession) -> SyncResult:
    """Bring the copy up to date: one sync at a time, at most every
    SYNC_EVERY_SECONDS (a failed one counts), within SYNC_SECONDS.
    ``SyncFailed`` with the reason when tastytrade fails or the deadline
    passes, and again for a visit inside the minute after; ``VaultUnavailable``
    without a key, when nothing is read or written."""
    global _last_failure
    if not vault.is_configured():
        raise vault.VaultUnavailable("the trade copy's key isn't set on the server")
    async with _lock:
        if _synced_at is not None and _clock() - _synced_at < SYNC_EVERY_SECONDS:
            if _last_failure is not None:
                raise SyncFailed(_last_failure)
            return SyncResult(new=0, replaced=0, skipped=True)
        try:
            async with asyncio.timeout(SYNC_SECONDS):
                result = await _sync(session)
        except (tt.TastytradeUnavailable, tt.TastytradeNotFound, TimeoutError) as exc:
            await session.rollback()  # a deadline can land mid-write; the listing needs a clean session
            _last_failure = owner_positions.failure_reason(exc)
            raise SyncFailed(_last_failure) from exc
        except Exception:
            _last_failure = "the last update failed"  # the error itself goes to the log
            raise
        finally:
            _stamp()
        _last_failure = None
        return result


def _stamp() -> None:
    global _synced_at
    _synced_at = _clock()


async def _sync(session: AsyncSession) -> SyncResult:
    rows = await store.stored(session)
    known = {row.id: row.estimated_fee for row in rows}
    latest = _latest_date([payload for _, payload in await asyncio.to_thread(_opened, rows)])
    await session.rollback()  # no connection held while tastytrade is read
    start = latest - timedelta(days=OVERLAP_DAYS) if latest else None
    new: list[dict[str, Any]] = []
    replacements: list[dict[str, Any]] = []
    accounts = (await owner_positions.account_numbers())[: owner_positions.MAX_ACCOUNTS]
    numbers = {number: index for index, number in enumerate(accounts, start=1)}
    for number, index in numbers.items():
        try:
            items = await _transactions(number, start)
        except tt.TastytradeNotFound:
            continue  # a closed account; the rest still sync
        for item in items:
            tid = _id(item)
            if tid is None:
                continue
            estimated = item.get("is-estimated-fee") is True
            if tid not in known:
                new.append(_sealed(tid, item, index, numbers))
                known[tid] = estimated
            elif known[tid] and not estimated:
                replacements.append(_sealed(tid, item, index, numbers))
                known[tid] = False
    written = await store.insert(session, new)
    replaced = 0
    for row in replacements:
        replaced += await store.replace_estimated(session, row)
    logger.info("owner trades: %d new, %d replaced", written, replaced)
    return SyncResult(new=written, replaced=replaced)


def _signed(amount: Any, effect: Any) -> float | None:
    number = owner_positions.finite_number(amount)
    return None if number is None else (-number if effect == "Debit" else number)


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _trade(tid: int, p: dict[str, Any]) -> OwnerTrade:
    fees = [owner_positions.finite_number(p.get(name)) for name in FEES]
    return OwnerTrade(
        id=tid,
        account=p.get("account") if isinstance(p.get("account"), int) else 0,
        executed_at=_text(p.get("executed-at")),
        date=_text(p.get("transaction-date")),
        type=_text(p.get("transaction-type")),
        sub_type=_text(p.get("transaction-sub-type")),
        action=_text(p.get("action")),
        symbol=_text(p.get("symbol")),
        underlying=_text(p.get("underlying-symbol")),
        instrument_type=_text(p.get("instrument-type")),
        quantity=owner_positions.finite_number(p.get("quantity")),
        price=owner_positions.finite_number(p.get("price")),
        value=_signed(p.get("value"), p.get("value-effect")),
        fees=sum(abs(f) for f in fees if f is not None),
        net_value=_signed(p.get("net-value"), p.get("net-value-effect")),
        description=_text(p.get("description")),
    )


async def list_trades(session: AsyncSession) -> list[OwnerTrade]:
    """Every stored trade, opened, newest first. ``VaultUnavailable`` without
    a key, an empty table included: no key is no copy, not an empty one."""
    if not vault.is_configured():
        raise vault.VaultUnavailable("the trade copy's key isn't set on the server")
    rows = await store.stored(session)
    trades = [_trade(tid, payload) for tid, payload in await asyncio.to_thread(_opened, rows)]
    return sorted(trades, key=lambda t: (t.executed_at or "", t.id), reverse=True)


def csv_cell(value: Any) -> str:
    """A value as a CSV cell; text a spreadsheet would run is prefixed with '."""
    if value is None:
        return ""
    if isinstance(value, str):
        # Some importers trim leading spaces and newlines before reading a formula.
        return f"'{value}" if value.lstrip(" \t\r\n").startswith(_FORMULA_START) or value.startswith(_FORMULA_START) else value
    return str(value)


def csv_text(trades: list[OwnerTrade]) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for trade in trades:
        row = trade.model_dump()
        writer.writerow([csv_cell(row[column]) for column in CSV_COLUMNS])
    return out.getvalue()
