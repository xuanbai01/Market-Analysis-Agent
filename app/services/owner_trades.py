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
from datetime import UTC, date, datetime, timedelta
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
# A whole read this often (and first in each process): what tastytrade posts
# late under an older date, or a new account's history, is caught then.
FULL_READ_EVERY_SECONDS = 24 * 3600.0
# A whole read asks from here, so no default window on tastytrade's side can
# leave the oldest trades out.
FULL_READ_FROM = date(2000, 1, 1)
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
_full_read_at: float | None = None
# Why the last sync failed, until one works: a visit inside the minute
# after it is told so, not that the copy was updated.
_last_failure: str | None = None
_lock = asyncio.Lock()  # one sync at a time


def reset() -> None:
    """Forget when the last sync ran and how (tests)."""
    global _synced_at, _full_read_at, _last_failure, _lock
    _synced_at, _full_read_at, _last_failure, _lock = None, None, None, asyncio.Lock()


# Swapped in tests.
def _clock() -> float:
    return time.monotonic()


def _id(item: dict[str, Any]) -> int | None:
    value = item.get("id")
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)  # the same id, sent as text
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _scrubbed(value: Any, numbers: dict[str, int]) -> Any:
    """Free text with any account number in it replaced by "account N"."""
    if not isinstance(value, str):
        return value
    for number, index in numbers.items():
        value = value.replace(number, f"account {index}")
    return value


def _estimated(item: dict[str, Any]) -> bool:
    """Whether tastytrade's fees for it are still estimates (a JSON true, or "true")."""
    value = item.get("is-estimated-fee")
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def _sealed(tid: int, item: dict[str, Any], account: int, numbers: dict[str, int]) -> dict[str, Any]:
    payload = {key: _scrubbed(item[key], numbers) for key in KEPT if key in item}
    payload["account"] = account
    estimated = _estimated(item)
    nonce, ciphertext = vault.seal(payload, tid, estimated_fee=estimated)
    return {
        "id": tid, "key_version": vault.KEY_VERSION, "nonce": nonce, "ciphertext": ciphertext,
        "estimated_fee": estimated,
    }


@dataclass(frozen=True)
class _Stored:
    """A stored row's columns, read out of the session so it can be let go."""

    id: int
    key_version: int
    nonce: bytes
    ciphertext: bytes
    estimated_fee: bool


def _detached(rows: list[Any]) -> list[_Stored]:
    return [_Stored(r.id, r.key_version, r.nonce, r.ciphertext, r.estimated_fee) for r in rows]


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
        items = owner_positions.items_of(payload, strict=True)
        found += items
        pagination = payload.get("pagination") if isinstance(payload, dict) else None
        pages = _whole(pagination.get("total-pages")) if isinstance(pagination, dict) else None
        # Without a page count, a short page is the last one.
        if (len(items) < PER_PAGE) if pages is None else (page + 1 >= pages):
            return found
    logger.warning("owner trades: more than %d pages of history; the rest isn't read", MAX_PAGES)
    return found


def _whole(value: Any) -> int | None:
    """A page count tastytrade sent, as a number (2 or 2.0) or as digits;
    none under 1, so a garbled count falls back to reading on while pages are full."""
    if isinstance(value, str) and value.isascii() and value.isdigit():
        value = int(value)
    elif isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 1 else None


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
            await _roll_back(session)  # a deadline can land mid-write; the listing needs a clean session
            # The deadline covers the database's part too: don't blame tastytrade for it.
            too_long = isinstance(exc, TimeoutError)
            _last_failure = f"the update took too long (over {SYNC_SECONDS:.0f} s)" if too_long else owner_positions.failure_reason(exc)
            raise SyncFailed(_last_failure) from exc
        except vault.VaultUnavailable:
            raise  # a row that doesn't open stays loud: a 503
        except asyncio.CancelledError:
            # The visit went away mid-sync, perhaps after some rows were
            # written: the next visit inside the minute is told so.
            _last_failure = "the last update was cut short"
            raise
        except Exception as exc:
            # The database, say, dropping the connection mid-write: what's
            # stored is still shown. The log names the error's type only: its
            # text could carry a request path with the account number.
            logger.error("owner trades: the sync failed (%s)", type(exc).__name__)
            await _roll_back(session)
            _last_failure = "the copy couldn't be updated"
            raise SyncFailed(_last_failure) from exc
        finally:
            _stamp()
        _last_failure = None
        return result


async def _roll_back(session: AsyncSession) -> None:
    """Leave the session clean for the listing; a lost connection may refuse
    even this, and the next statement takes a fresh one."""
    try:
        await session.rollback()
    except Exception:
        logger.warning("owner trades: the rollback after a failed sync failed too")


def _stamp() -> None:
    global _synced_at
    _synced_at = _clock()


async def _sync(session: AsyncSession) -> SyncResult:
    global _full_read_at
    rows = _detached(await store.stored(session))
    await session.rollback()  # no connection held while the copy is decrypted or tastytrade read
    known = {row.id: row.estimated_fee for row in rows}
    full = _full_read_at is None or _clock() - _full_read_at >= FULL_READ_EVERY_SECONDS
    latest = None if full else _latest_date([payload for _, payload in await asyncio.to_thread(_opened, rows)])
    start = latest - timedelta(days=OVERLAP_DAYS) if latest else FULL_READ_FROM
    to_add: list[tuple[int, dict[str, Any], int]] = []
    to_replace: list[tuple[int, dict[str, Any], int]] = []
    every = await owner_positions.account_numbers()
    if len(every) > owner_positions.MAX_ACCOUNTS:
        logger.warning("owner trades: %d accounts past the cap of %d aren't copied", len(every) - owner_positions.MAX_ACCOUNTS, owner_positions.MAX_ACCOUNTS)
    accounts = every[: owner_positions.MAX_ACCOUNTS]
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
            estimated = _estimated(item)
            if tid not in known:
                to_add.append((tid, item, index))
                known[tid] = estimated
            elif known[tid] and not estimated:
                to_replace.append((tid, item, index))
                known[tid] = False
    # Sealing is CPU (a first sync seals the whole history): off the event loop.
    new = await asyncio.to_thread(lambda: [_sealed(tid, item, index, numbers) for tid, item, index in to_add])
    replacements = await asyncio.to_thread(lambda: [_sealed(tid, item, index, numbers) for tid, item, index in to_replace])
    written = await store.insert(session, new)
    replaced = 0
    for row in replacements:
        replaced += await store.replace_estimated(session, row)
    if full:
        _full_read_at = _clock()
    logger.info("owner trades: %d new, %d replaced%s", written, replaced, " (full read)" if full else "")
    return SyncResult(new=written, replaced=replaced)


def _signed(amount: Any, effect: Any) -> float | None:
    """Money in positive, out negative; which way isn't guessed for an amount
    without a credit or debit."""
    number = owner_positions.finite_number(amount)
    if number is None:
        return None
    if effect == "Debit":
        return -abs(number)
    if effect == "Credit":
        return abs(number)
    return 0.0 if number == 0 else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _fee(amount: Any, effect: Any) -> float:
    """A fee's cost: a fee credited back (a rebate) counts against the rest."""
    number = owner_positions.finite_number(amount)
    if number is None:
        return 0.0
    return -abs(number) if effect == "Credit" else abs(number)


def _trade(tid: int, p: dict[str, Any]) -> OwnerTrade:
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
        # Rounded off float noise: the CSV writes 1.14, not 1.1400000000000001.
        fees=round(sum(_fee(p.get(name), p.get(f"{name}-effect")) for name in FEES), 6),
        net_value=_signed(p.get("net-value"), p.get("net-value-effect")),
        description=_text(p.get("description")),
    )


async def list_trades(session: AsyncSession) -> list[OwnerTrade]:
    """Every stored trade, opened, newest first. ``VaultUnavailable`` without
    a key, an empty table included: no key is no copy, not an empty one."""
    if not vault.is_configured():
        raise vault.VaultUnavailable("the trade copy's key isn't set on the server")
    rows = _detached(await store.stored(session))
    await session.rollback()  # no connection held while the copy is decrypted
    trades = [_trade(tid, payload) for tid, payload in await asyncio.to_thread(_opened, rows)]
    return sorted(trades, key=_when, reverse=True)


def _when(trade: OwnerTrade) -> tuple[datetime, int]:
    """When it happened, for the order: its time, else its date's start (UTC)."""
    for text in (trade.executed_at, trade.date):
        try:
            when = datetime.fromisoformat(text) if text else None
        except ValueError:
            continue
        if when is not None:
            return (when if when.tzinfo else when.replace(tzinfo=UTC), trade.id)
    return (datetime.min.replace(tzinfo=UTC), trade.id)


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
