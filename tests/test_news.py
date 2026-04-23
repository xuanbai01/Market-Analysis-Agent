from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.news import NewsItemModel


def _make_news(
    id: str, title: str, ts: datetime, source: str = "reuters"
) -> NewsItemModel:
    return NewsItemModel(
        id=id,
        ts=ts,
        title=title,
        url=f"https://example.com/{id}",
        source=source,
    )


async def test_list_news_empty_by_default(client: AsyncClient) -> None:
    resp = await client.get("/v1/news")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "next_cursor": None}


async def test_list_news_returns_recent_items_newest_first(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _make_news("a", "Older headline", now - timedelta(hours=2)),
            _make_news("b", "Newer headline", now - timedelta(minutes=5)),
        ]
    )
    await db_session.flush()

    resp = await client.get("/v1/news")
    assert resp.status_code == 200
    titles = [item["title"] for item in resp.json()["items"]]
    assert titles == ["Newer headline", "Older headline"]


async def test_list_news_excludes_items_older_than_window(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    now = datetime.now(UTC)
    db_session.add_all(
        [
            _make_news("recent", "In window", now - timedelta(hours=1)),
            _make_news("ancient", "Out of window", now - timedelta(hours=48)),
        ]
    )
    await db_session.flush()

    resp = await client.get("/v1/news", params={"hours": 24})
    assert resp.status_code == 200
    ids = [item["id"] for item in resp.json()["items"]]
    assert ids == ["recent"]


async def test_news_detail_returns_item(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(_make_news("xyz", "A headline", datetime.now(UTC)))
    await db_session.flush()

    resp = await client.get("/v1/news/xyz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "xyz"
    assert body["title"] == "A headline"


async def test_news_detail_returns_404_for_missing(client: AsyncClient) -> None:
    resp = await client.get("/v1/news/does-not-exist")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
