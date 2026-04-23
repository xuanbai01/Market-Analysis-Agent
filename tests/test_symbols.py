from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.symbols import Symbol


async def test_list_symbols_empty_by_default(client: AsyncClient) -> None:
    resp = await client.get("/v1/symbols")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_symbols_returns_seeded_rows(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Symbol(symbol="NVDA", name="NVIDIA Corp"),
            Symbol(symbol="SPY", name="SPDR S&P 500 ETF"),
        ]
    )
    await db_session.flush()

    resp = await client.get("/v1/symbols")
    assert resp.status_code == 200
    body = resp.json()
    assert {row["symbol"] for row in body} == {"NVDA", "SPY"}


async def test_list_symbols_respects_query_filter(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add_all(
        [
            Symbol(symbol="NVDA", name="NVIDIA Corp"),
            Symbol(symbol="AAPL", name="Apple Inc"),
        ]
    )
    await db_session.flush()

    resp = await client.get("/v1/symbols", params={"query": "NVDA"})
    assert resp.status_code == 200
    assert [row["symbol"] for row in resp.json()] == ["NVDA"]


async def test_create_symbol_persists_row(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    resp = await client.post("/v1/symbols", json={"symbol": "tsla", "name": "Tesla"})
    assert resp.status_code == 201
    assert resp.json() == {"symbol": "TSLA", "name": "Tesla"}

    listed = await client.get("/v1/symbols")
    assert [row["symbol"] for row in listed.json()] == ["TSLA"]


async def test_create_symbol_rejects_missing_fields(client: AsyncClient) -> None:
    resp = await client.post("/v1/symbols", json={})
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/problem+json")
