"""The trade copy's routes: behind the owner key, synced then listed, the
copy as it stands when tastytrade is down, 503 without the vault key, and a
CSV a spreadsheet can't be tricked by. Services are faked here."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.api.v1 import dependencies as deps
from app.api.v1.dependencies import get_session
from app.api.v1.routers import owner as owner_router
from app.core import settings as settings_module
from app.main import app
from app.schemas.owner import OwnerTrade
from app.services import owner_vault
from app.services.owner_trades import SyncFailed

OWNER_KEY = "o" * 40  # plainly fake
TRADES = [
    OwnerTrade(id=2, account=1, executed_at="2026-11-13T15:30:00+00:00", symbol="NVDA", action="Buy to Close",
               net_value=-120.5, fees=1.1, description="=HYPERLINK(\"http://x\")"),
    OwnerTrade(id=1, account=1, executed_at="2026-10-01T15:30:00+00:00", symbol="NVDA", action="Sell to Open",
               net_value=478.86, fees=1.14, description="Sold 1 NVDA"),
]


class _Calls:
    def __init__(self) -> None:
        self.synced = 0
        self.sync_fail: Exception | None = None
        self.list_fail: Exception | None = None


@pytest_asyncio.fixture
async def client(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[AsyncClient, _Calls]]:
    calls = _Calls()

    async def _session() -> AsyncIterator[None]:
        yield None

    async def sync(_session: Any) -> None:
        calls.synced += 1
        if calls.sync_fail:
            raise calls.sync_fail

    async def list_trades(_session: Any) -> list[OwnerTrade]:
        if calls.list_fail:
            raise calls.list_fail
        return TRADES

    monkeypatch.setattr(settings_module.settings, "BACKEND_SHARED_SECRET", "")
    monkeypatch.setattr(settings_module.settings, "OWNER_KEY", SecretStr(OWNER_KEY))
    monkeypatch.setattr(owner_router, "sync", sync)
    monkeypatch.setattr(owner_router, "list_trades", list_trades)
    deps.reset_owner_failures_for_tests()
    app.dependency_overrides[get_session] = _session
    try:
        transport = ASGITransport(app=app, raise_app_exceptions=False)
        async with AsyncClient(transport=transport, base_url="http://test", headers={deps.OWNER_HEADER: OWNER_KEY}) as ac:
            yield ac, calls
    finally:
        app.dependency_overrides.pop(get_session, None)


async def test_the_trades_are_synced_then_listed(client: tuple[AsyncClient, _Calls]) -> None:
    ac, calls = client
    resp = await ac.get("/v1/owner/trades")
    assert resp.status_code == 200 and calls.synced == 1
    body = resp.json()
    assert body["synced"] is True and [t["id"] for t in body["trades"]] == [2, 1]
    assert resp.headers["Cache-Control"] == "no-store"


async def test_the_trades_come_with_their_journal(client: tuple[AsyncClient, _Calls], monkeypatch: pytest.MonkeyPatch) -> None:
    """The journal is read from the same copy on each visit (PR D)."""
    ac, _calls = client
    rows = [
        OwnerTrade(id=1, account=1, executed_at="2026-10-01T15:00:00+00:00", action="Sell to Open", symbol="NVDA  261218C00175000",
                   underlying="NVDA", instrument_type="Equity Option", quantity=1, net_value=480.0, order_id=10),
        OwnerTrade(id=2, account=1, executed_at="2026-10-21T15:00:00+00:00", action="Buy to Close", symbol="NVDA  261218C00175000",
                   underlying="NVDA", instrument_type="Equity Option", quantity=1, net_value=-200.0, order_id=11),
    ]

    async def list_trades(_session: Any) -> list[OwnerTrade]:
        return rows

    monkeypatch.setattr(owner_router, "list_trades", list_trades)
    journal = (await ac.get("/v1/owner/trades")).json()["journal"]
    (position,) = journal["positions"]
    assert (position["structure"], position["status"], position["realized"]) == ("short call", "closed", 280.0)
    assert journal["totals"]["realized"] == 280.0


async def test_with_tastytrade_down_the_copy_stands_and_says_why(client: tuple[AsyncClient, _Calls]) -> None:
    ac, calls = client
    calls.sync_fail = SyncFailed("tastytrade took too long to answer")
    resp = await ac.get("/v1/owner/trades")
    body = resp.json()
    assert resp.status_code == 200
    assert body["synced"] is False and len(body["trades"]) == 2
    assert body["reason"] == "tastytrade took too long to answer"


async def test_without_the_vault_key_it_is_a_503(client: tuple[AsyncClient, _Calls]) -> None:
    ac, calls = client
    calls.sync_fail = owner_vault.VaultUnavailable("the trade copy's key isn't set on the server")
    resp = await ac.get("/v1/owner/trades")
    assert resp.status_code == 503 and resp.headers["Cache-Control"] == "no-store"
    calls.list_fail = owner_vault.VaultUnavailable("a stored trade doesn't open with this key")
    assert (await ac.get("/v1/owner/trades.csv")).status_code == 503


async def test_the_csv_is_a_download_a_spreadsheet_cannot_be_tricked_by(client: tuple[AsyncClient, _Calls]) -> None:
    ac, _calls = client
    resp = await ac.get("/v1/owner/trades.csv")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert resp.headers["content-disposition"] == 'attachment; filename="trades.csv"'
    lines = resp.text.splitlines()
    assert lines[0].startswith("id,account,executed_at")
    assert "'=HYPERLINK" in lines[1] and ",-120.5," in lines[1]


async def test_the_trades_need_the_owner_key(client: tuple[AsyncClient, _Calls]) -> None:
    ac, calls = client
    for path in ("/v1/owner/trades", "/v1/owner/trades.csv"):
        assert (await ac.get(path, headers={deps.OWNER_HEADER: "wrong"})).status_code == 403
    assert calls.synced == 0
