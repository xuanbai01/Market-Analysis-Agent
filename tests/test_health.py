from httpx import AsyncClient


async def test_health_returns_ok_when_db_reachable(client: AsyncClient) -> None:
    resp = await client.get("/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"status": "ok", "db": True}


async def test_root_returns_hello(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    assert resp.json() == {"message": "Hello from Market Analysis Agent"}
