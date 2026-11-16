"""The owner's trade copy (ADR 0009, amended): sync tastytrade's
transactions into the encrypted table, list them back.

The store and tastytrade are faked; ``test_owner_trade_store`` covers the
table itself. Account numbers never reach a stored row (each row keeps the
account's 1-based number), and no connection is held during the fetch.
"""
from __future__ import annotations

import base64
from datetime import date
from typing import Any

import pytest
from pydantic import SecretStr

from app.core import settings as settings_module
from app.services import owner_positions
from app.services import owner_trades as ot
from app.services import owner_vault as vault
from app.services import tastytrade_client as tt

ACCOUNT = "5WZ9QX7T"  # distinctive: never stored
KEY = base64.b64encode(bytes(range(32))).decode()


def _txn(tid: int, day: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": tid, "account-number": ACCOUNT, "executed-at": f"{day}T15:30:00.000+00:00", "transaction-date": day,
        "transaction-type": "Trade", "transaction-sub-type": "Sell to Open", "action": "Sell to Open",
        "symbol": "NVDA  261218C00175000", "underlying-symbol": "NVDA", "instrument-type": "Equity Option",
        "description": "Sold 1 NVDA 12/18/26 Call 175.00 @ 4.80", "quantity": "1.0", "price": "4.8",
        "value": "480.0", "value-effect": "Credit", "commission": "1.0", "commission-effect": "Debit",
        "clearing-fees": "0.1", "clearing-fees-effect": "Debit", "regulatory-fees": "0.04", "regulatory-fees-effect": "Debit",
        "net-value": "478.86", "net-value-effect": "Credit", "is-estimated-fee": False, **extra,
    }


class _Row:
    def __init__(self, row: dict[str, Any]) -> None:
        self.__dict__.update(row)


class _Session:
    def __init__(self) -> None:
        self.in_tx = False

    async def rollback(self) -> None:
        self.in_tx = False


class _World:
    def __init__(self) -> None:
        self.session = _Session()
        self.rows: dict[int, dict[str, Any]] = {}
        self.history: list[dict[str, Any]] = []
        self.calls: list[dict[str, Any]] = []
        self.per_page = 2000
        self.fail: Exception | None = None
        self.clock = [0.0]
        self.pages_as: str = "int"  # how the page count comes: int, text, float or absent
        self.insert_fail: Exception | None = None

    def later(self, seconds: float = 0.0) -> None:
        """Past the sync spacing, and ``seconds`` more."""
        self.clock[0] += ot.SYNC_EVERY_SECONDS + 1 + seconds

    async def stored(self, session: _Session) -> list[_Row]:
        session.in_tx = True
        return [_Row(r) for _, r in sorted(self.rows.items())]

    async def insert(self, session: _Session, rows: list[dict[str, Any]]) -> int:
        if self.insert_fail:
            session.in_tx = True  # the write had begun
            raise self.insert_fail
        written = 0
        for row in rows:
            if row["id"] not in self.rows:
                self.rows[row["id"]] = row
                written += 1
        return written

    async def replace_estimated(self, session: _Session, row: dict[str, Any]) -> bool:
        if self.rows.get(row["id"], {}).get("estimated_fee"):
            self.rows[row["id"]] = row
            return True
        return False

    async def get(self, path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        import asyncio

        await asyncio.sleep(0)  # a real read yields: concurrent syncs interleave here
        assert not self.session.in_tx, "a database connection was held during the fetch"
        if self.fail:
            raise self.fail
        if path == "/customers/me/accounts":
            return {"data": {"items": [{"account": {"account-number": ACCOUNT}}]}}
        assert path == f"/accounts/{ACCOUNT}/transactions"
        params = params or {}
        self.calls.append(params)
        start = params.get("start-date")
        matching = [t for t in self.history if start is None or t["transaction-date"] >= start]
        offset = params["page-offset"]
        page = matching[offset * self.per_page:(offset + 1) * self.per_page]
        pages = max(1, -(-len(matching) // self.per_page))
        if self.pages_as == "absent":
            return {"data": {"items": page}}
        count: Any = {"int": pages, "text": str(pages), "float": float(pages)}[self.pages_as]
        return {"data": {"items": page}, "pagination": {"total-pages": count, "page-offset": offset}}


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> _World:
    w = _World()
    monkeypatch.setattr(settings_module.settings, "OWNER_VAULT_KEY", SecretStr(KEY))
    monkeypatch.setattr(ot.store, "stored", w.stored)
    monkeypatch.setattr(ot.store, "insert", w.insert)
    monkeypatch.setattr(ot.store, "replace_estimated", w.replace_estimated)
    monkeypatch.setattr(tt, "get", w.get)
    monkeypatch.setattr(ot, "_clock", lambda: w.clock[0])
    owner_positions.reset()
    ot.reset()
    yield w
    owner_positions.reset()
    ot.reset()


async def _sync(world: _World) -> Any:
    return await ot.sync(world.session)  # type: ignore[arg-type]


async def test_the_first_sync_copies_every_transaction_sealed(world: _World) -> None:
    world.history = [_txn(1, "2026-10-01"), _txn(2, "2026-11-13")]
    result = await _sync(world)
    assert (result.new, result.replaced) == (2, 0)
    assert "start-date" not in world.calls[0]
    for tid, row in world.rows.items():
        assert set(row) == {"id", "key_version", "nonce", "ciphertext", "estimated_fee"}
        assert b"NVDA" not in row["ciphertext"] and ACCOUNT.encode() not in row["ciphertext"]
        payload = vault.unseal(row["nonce"], row["ciphertext"], tid, key_version=1, estimated_fee=row["estimated_fee"])
        assert payload["account"] == 1 and "account-number" not in payload  # numbered, never named


async def test_a_later_sync_reads_back_a_week_and_adds_only_new_ones(world: _World) -> None:
    world.history = [_txn(1, "2026-10-01"), _txn(2, "2026-11-13")]
    await _sync(world)
    world.history.append(_txn(3, "2026-11-16"))
    world.later()
    result = await _sync(world)
    assert (result.new, result.replaced) == (1, 0)
    assert world.calls[-1]["start-date"] == date(2026, 11, 6).isoformat()


async def test_estimated_fees_are_replaced_once_final_and_only_then(world: _World) -> None:
    world.history = [_txn(1, "2026-11-13", **{"is-estimated-fee": True, "net-value": "478.00"})]
    await _sync(world)
    assert world.rows[1]["estimated_fee"] is True
    world.history = [_txn(1, "2026-11-13", **{"is-estimated-fee": False, "net-value": "478.86"})]
    world.later()
    assert (await _sync(world)).replaced == 1
    row = world.rows[1]
    assert vault.unseal(row["nonce"], row["ciphertext"], 1, key_version=1, estimated_fee=False)["net-value"] == "478.86"
    world.later()
    assert (await _sync(world)).replaced == 0  # a final row is never touched again


async def test_every_page_is_read(world: _World) -> None:
    world.per_page = 2
    world.history = [_txn(i, f"2026-10-{i:02d}") for i in range(1, 6)]
    result = await _sync(world)
    assert result.new == 5
    assert [c["page-offset"] for c in world.calls] == [0, 1, 2]
    assert all(c["per-page"] == 2000 for c in world.calls)  # what we ask for; the fake pages by 2


async def test_syncs_are_spaced(world: _World) -> None:
    world.history = [_txn(1, "2026-10-01")]
    await _sync(world)
    calls = len(world.calls)
    assert (await _sync(world)).skipped is True
    assert len(world.calls) == calls


async def test_a_row_without_an_id_is_skipped(world: _World) -> None:
    world.history = [_txn(1, "2026-10-01"), {**_txn(2, "2026-10-02"), "id": "x"}, {**_txn(3, "2026-10-03"), "id": None}]
    assert (await _sync(world)).new == 1


async def test_without_the_vault_key_nothing_is_fetched_or_stored(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_module.settings, "OWNER_VAULT_KEY", SecretStr(""))
    world.history = [_txn(1, "2026-10-01")]
    with pytest.raises(vault.VaultUnavailable):
        await _sync(world)
    assert world.calls == [] and world.rows == {}


async def test_the_list_is_newest_first_with_signed_amounts(world: _World) -> None:
    world.history = [
        _txn(1, "2026-10-01"),
        _txn(2, "2026-11-13", **{"action": "Buy to Close", "net-value": "120.5", "net-value-effect": "Debit"}),
    ]
    await _sync(world)
    trades = await ot.list_trades(world.session)  # type: ignore[arg-type]
    assert [t.id for t in trades] == [2, 1]
    assert trades[0].net_value == -120.5 and trades[1].net_value == 478.86
    assert trades[1].fees == 1.14  # not 1.1400000000000001 in the CSV
    assert trades[1].account == 1 and trades[1].underlying == "NVDA"


def test_a_csv_cell_that_a_spreadsheet_would_run_is_defused() -> None:
    assert ot.csv_cell("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert ot.csv_cell("+1") == "'+1" and ot.csv_cell("@x") == "'@x" and ot.csv_cell("-x") == "'-x"
    assert ot.csv_cell("Sold 1 NVDA") == "Sold 1 NVDA"
    assert ot.csv_cell(-120.5) == "-120.5"  # numbers stay numbers


async def test_an_account_number_in_free_text_is_scrubbed_before_sealing(world: _World) -> None:
    world.history = [_txn(1, "2026-10-01", description=f"Transfer to {ACCOUNT}", transaction_type="Money Movement")]
    await _sync(world)
    row = world.rows[1]
    payload = vault.unseal(row["nonce"], row["ciphertext"], 1, key_version=1, estimated_fee=False)
    assert payload["description"] == "Transfer to account 1"


async def test_a_failed_sync_is_spaced_too_and_still_says_it_failed(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    """A visit inside the minute after a failed sync isn't told the copy was
    updated (#129's AI review); the next sync that works clears it."""
    clock = [0.0]
    monkeypatch.setattr(ot, "_clock", lambda: clock[0])
    world.history = [_txn(1, "2026-10-01")]
    world.fail = tt.TastytradeUnavailable(f"tastytrade answered 503 for /accounts/{ACCOUNT}/transactions")
    with pytest.raises(ot.SyncFailed) as first:
        await _sync(world)
    assert ACCOUNT not in str(first.value)  # the reason is the masked one
    world.fail = None
    calls = len(world.calls)
    with pytest.raises(ot.SyncFailed):
        await _sync(world)  # not asked again within the minute, and not reported as synced
    assert len(world.calls) == calls
    clock[0] = ot.SYNC_EVERY_SECONDS + 1
    assert (await _sync(world)).new == 1
    clock[0] += 1
    assert (await _sync(world)).skipped is True


async def test_a_sync_that_runs_too_long_says_so_and_lets_go(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    """The deadline's TimeoutError is a failed sync, not a 500 (#129's AI review)."""
    import asyncio

    slow = world.get

    async def get(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        await asyncio.sleep(1)
        return await slow(path, params, op=op)

    monkeypatch.setattr(tt, "get", get)
    monkeypatch.setattr(ot, "SYNC_SECONDS", 0.01)
    with pytest.raises(ot.SyncFailed, match="^the update took too long") as failed:
        await _sync(world)
    assert "tastytrade" not in str(failed.value)  # the deadline covers the database's part too
    assert world.session.in_tx is False  # rolled back, ready for the listing


async def test_listing_without_the_key_refuses_even_with_nothing_stored(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    """The CSV route lists without syncing: an empty table mustn't read as an
    empty copy when there's no key (#129's AI review)."""
    monkeypatch.setattr(settings_module.settings, "OWNER_VAULT_KEY", SecretStr(""))
    with pytest.raises(vault.VaultUnavailable):
        await ot.list_trades(world.session)  # type: ignore[arg-type]


async def test_two_visits_at_once_sync_once(world: _World) -> None:
    import asyncio

    world.history = [_txn(1, "2026-10-01")]
    first, second = await asyncio.gather(_sync(world), _sync(world))
    assert sorted([first.skipped, second.skipped]) == [False, True]
    assert len(world.calls) == 1


async def test_a_closed_account_is_skipped(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    real = world.get

    async def two(path: str, params: dict[str, Any] | None = None, *, op: str) -> dict[str, Any]:
        if path == "/customers/me/accounts":
            return {"data": {"items": [{"account": {"account-number": "GONE0001"}}, {"account": {"account-number": ACCOUNT}}]}}
        if path == "/accounts/GONE0001/transactions":
            raise tt.TastytradeNotFound("/accounts/***/transactions")
        return await real(path, params, op=op)

    monkeypatch.setattr(tt, "get", two)
    world.history = [_txn(1, "2026-10-01")]
    assert (await _sync(world)).new == 1


def test_a_formula_behind_spaces_or_a_newline_is_defused_too() -> None:
    assert ot.csv_cell(" =1+1") == "' =1+1"
    assert ot.csv_cell("\n=1+1") == "'\n=1+1"


async def test_a_full_read_once_a_day_catches_what_was_posted_late(world: _World) -> None:
    """The week read back misses a correction tastytrade posts later under an
    older date, or a new account's history; a full read a day catches it
    (#129's second AI review)."""
    world.history = [_txn(1, "2026-10-01"), _txn(2, "2026-11-13")]
    await _sync(world)
    assert "start-date" not in world.calls[-1]  # the first read in a process is whole
    world.history.append(_txn(3, "2026-11-02"))  # dated before the week read back
    world.later()
    assert (await _sync(world)).new == 0
    assert world.calls[-1]["start-date"] == date(2026, 11, 6).isoformat()
    world.later(ot.FULL_READ_EVERY_SECONDS)
    assert (await _sync(world)).new == 1
    assert "start-date" not in world.calls[-1]


async def test_an_id_sent_as_digits_is_still_an_id(world: _World) -> None:
    world.history = [{**_txn(4, "2026-10-01"), "id": "4"}]
    assert (await _sync(world)).new == 1 and 4 in world.rows


async def test_a_fee_credited_back_lowers_the_fees(world: _World) -> None:
    world.history = [_txn(1, "2026-10-01", **{"commission": "0.5", "commission-effect": "Credit"})]
    await _sync(world)
    (trade,) = await ot.list_trades(world.session)  # type: ignore[arg-type]
    assert trade.fees == pytest.approx(-0.5 + 0.1 + 0.04)


async def test_a_database_failure_mid_write_is_a_failed_sync_not_a_500(world: _World) -> None:
    """Neon dropping the connection mid-write: the copy stands and says so,
    on a rolled-back session (#129's third AI review)."""
    world.history = [_txn(1, "2026-10-01")]
    world.insert_fail = RuntimeError("connection was closed in the middle of operation")
    with pytest.raises(ot.SyncFailed, match="couldn't be updated"):
        await _sync(world)
    assert world.session.in_tx is False


async def test_a_failed_sync_logs_the_error_s_kind_not_its_text(world: _World, caplog: pytest.LogCaptureFixture) -> None:
    """An unexpected error's text can carry a request path with the account
    number: the log names its type only (#129's fourth AI review)."""
    world.history = [_txn(1, "2026-10-01")]
    world.insert_fail = RuntimeError(f"lost the connection writing /accounts/{ACCOUNT}/transactions")
    with caplog.at_level("DEBUG"), pytest.raises(ot.SyncFailed):
        await _sync(world)
    assert "RuntimeError" in caplog.text
    assert ACCOUNT not in caplog.text


async def test_sealing_runs_off_the_event_loop(world: _World, monkeypatch: pytest.MonkeyPatch) -> None:
    """A first sync seals the whole history: CPU that mustn't hold up other
    requests (#129's third AI review)."""
    import threading

    threads: list[bool] = []
    seal = vault.seal

    def recording(*args: Any, **kwargs: Any) -> Any:
        threads.append(threading.current_thread() is threading.main_thread())
        return seal(*args, **kwargs)

    monkeypatch.setattr(vault, "seal", recording)
    world.history = [_txn(1, "2026-10-01"), _txn(2, "2026-10-02")]
    await _sync(world)
    assert threads == [False, False]


@pytest.mark.parametrize("pages_as", ["text", "float", "absent"])
async def test_every_page_is_read_however_the_count_comes(world: _World, monkeypatch: pytest.MonkeyPatch, pages_as: str) -> None:
    """A count as digits or as 2.0, or none at all with a full page: the read
    goes on, rather than keep the first page as the whole history (#129's
    AI reviews)."""
    monkeypatch.setattr(ot, "PER_PAGE", 1)
    world.per_page = 1
    world.pages_as = pages_as
    world.history = [_txn(1, "2026-10-01"), _txn(2, "2026-10-02"), _txn(3, "2026-10-03")]
    assert (await _sync(world)).new == 3


async def test_a_trade_without_a_time_sorts_by_its_date(world: _World) -> None:
    late = {k: v for k, v in _txn(2, "2026-11-20").items() if k != "executed-at"}
    world.history = [_txn(1, "2026-11-13"), late]
    await _sync(world)
    trades = await ot.list_trades(world.session)  # type: ignore[arg-type]
    assert [t.id for t in trades] == [2, 1]

