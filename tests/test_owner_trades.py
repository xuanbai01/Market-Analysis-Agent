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

    async def stored(self, session: _Session) -> list[_Row]:
        session.in_tx = True
        return [_Row(r) for _, r in sorted(self.rows.items())]

    async def insert(self, session: _Session, rows: list[dict[str, Any]]) -> int:
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
        return {"data": {"items": page}, "pagination": {"total-pages": pages, "page-offset": offset}}


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> _World:
    w = _World()
    monkeypatch.setattr(settings_module.settings, "OWNER_VAULT_KEY", SecretStr(KEY))
    monkeypatch.setattr(ot.store, "stored", w.stored)
    monkeypatch.setattr(ot.store, "insert", w.insert)
    monkeypatch.setattr(ot.store, "replace_estimated", w.replace_estimated)
    monkeypatch.setattr(tt, "get", w.get)
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
        payload = vault.unseal(row["nonce"], row["ciphertext"], tid)
        assert payload["account"] == 1 and "account-number" not in payload  # numbered, never named


async def test_a_later_sync_reads_back_a_week_and_adds_only_new_ones(world: _World) -> None:
    world.history = [_txn(1, "2026-10-01"), _txn(2, "2026-11-13")]
    await _sync(world)
    world.history.append(_txn(3, "2026-11-16"))
    ot.reset()  # past the sync spacing
    result = await _sync(world)
    assert (result.new, result.replaced) == (1, 0)
    assert world.calls[-1]["start-date"] == date(2026, 11, 6).isoformat()


async def test_estimated_fees_are_replaced_once_final_and_only_then(world: _World) -> None:
    world.history = [_txn(1, "2026-11-13", **{"is-estimated-fee": True, "net-value": "478.00"})]
    await _sync(world)
    assert world.rows[1]["estimated_fee"] is True
    world.history = [_txn(1, "2026-11-13", **{"is-estimated-fee": False, "net-value": "478.86"})]
    ot.reset()
    assert (await _sync(world)).replaced == 1
    assert vault.unseal(world.rows[1]["nonce"], world.rows[1]["ciphertext"], 1)["net-value"] == "478.86"
    ot.reset()
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
    assert trades[1].fees == pytest.approx(1.14)
    assert trades[1].account == 1 and trades[1].underlying == "NVDA"


def test_a_csv_cell_that_a_spreadsheet_would_run_is_defused() -> None:
    assert ot.csv_cell("=HYPERLINK(\"x\")") == "'=HYPERLINK(\"x\")"
    assert ot.csv_cell("+1") == "'+1" and ot.csv_cell("@x") == "'@x" and ot.csv_cell("-x") == "'-x"
    assert ot.csv_cell("Sold 1 NVDA") == "Sold 1 NVDA"
    assert ot.csv_cell(-120.5) == "-120.5"  # numbers stay numbers
